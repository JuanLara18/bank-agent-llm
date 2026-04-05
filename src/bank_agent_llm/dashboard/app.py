"""Streamlit web dashboard for bank-agent-llm.

Launch via:  bank-agent dashboard
or directly: streamlit run src/bank_agent_llm/dashboard/app.py
"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="Bank Agent",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Bootstrap ─────────────────────────────────────────────────────────────────
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
os.chdir(_PROJECT_ROOT)

from dotenv import load_dotenv  # noqa: E402
load_dotenv(_PROJECT_ROOT / ".env")

# Custom CSS for compact KPI cards
st.markdown("""
<style>
[data-testid="metric-container"] { background: #1e1e2e; border-radius: 8px; padding: 12px 16px; }
.block-container { padding-top: 1.5rem; }
</style>
""", unsafe_allow_html=True)


# ── DB + taxonomy init ────────────────────────────────────────────────────────

@st.cache_resource
def _init_db() -> None:
    from bank_agent_llm.config import get_settings
    from bank_agent_llm.storage.database import init_engine
    settings = get_settings(str(_PROJECT_ROOT / "config" / "config.yaml"))
    init_engine(settings.database.url)


@st.cache_resource
def _get_taxonomy():
    from bank_agent_llm.enrichment.tags import get_taxonomy
    return get_taxonomy()


_init_db()
taxonomy = _get_taxonomy()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cop(v: float, compact: bool = False) -> str:
    if compact:
        if abs(v) >= 1_000_000:
            return f"${v/1_000_000:.1f}M"
        if abs(v) >= 1_000:
            return f"${v/1_000:.0f}K"
    return f"${v:,.0f}"


def _display(tag_id: str) -> str:
    if not tag_id or tag_id == "sin etiqueta":
        return "Sin etiqueta"
    return taxonomy.display_name(tag_id) or tag_id


def _primary(tags: list) -> str:
    if not tags:
        return "sin etiqueta"
    result = taxonomy.primary_tag(list(tags))
    return result or tags[0]


def _parent(tags: list) -> str:
    if not tags:
        return "sin etiqueta"
    return tags[0]


# ── Data loaders ─────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def _load_accounts() -> list[dict]:
    from bank_agent_llm.storage.database import get_session
    from bank_agent_llm.storage.repository import AccountRepository
    with get_session() as s:
        accs = AccountRepository(s).all()
    return [{"id": a.id, "bank_name": a.bank_name} for a in accs]


@st.cache_data(ttl=60)
def _load_transactions(
    date_from: date | None,
    date_to: date | None,
    account_ids: tuple[int, ...] | None,
    include_cancelled: bool,
) -> pd.DataFrame:
    from bank_agent_llm.storage.database import get_session
    from bank_agent_llm.storage.repository import StatsRepository
    ids = list(account_ids) if account_ids else None
    with get_session() as s:
        txs = StatsRepository(s).all_transactions(
            date_from=date_from, date_to=date_to,
            account_ids=ids, include_cancelled=include_cancelled,
        )
        rows = [{
            "id": t.id,
            "date": t.date,
            "amount": float(t.amount),
            "direction": t.direction,
            # Credit classification:
            #   pago_tarjeta  → payment made to the card (abono, reduces balance)
            #   reembolso     → merchant refund/credit (e.g. Rappi credit, Cursor refund)
            #   ingreso       → actual income (salary, transfer received) — rare in card stmts
            "credit_type": (
                "pago_tarjeta" if t.direction == "credit" and "pago-tarjeta" in (t.tags or [])
                else "ingreso" if t.direction == "credit" and "ingreso" in (t.tags or [])
                else "reembolso" if t.direction == "credit"
                else None
            ),
            "description": t.raw_description,
            "merchant": t.merchant_name or t.raw_description[:35],
            "tags_raw": list(t.tags) if t.tags else [],
            "primary_tag": _primary(list(t.tags) if t.tags else []),
            "parent_tag": _parent(list(t.tags) if t.tags else []),
            "tag_source": t.tag_source,
            "account_id": t.account_id,
        } for t in txs]
    df = pd.DataFrame(rows) if rows else pd.DataFrame()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df["primary_display"] = df["primary_tag"].apply(_display)
        df["parent_display"] = df["parent_tag"].apply(_display)
        df["month"] = df["date"].dt.to_period("M").astype(str)
        df["month_dt"] = df["date"].dt.to_period("M").dt.to_timestamp()
        df["weekday_num"] = df["date"].dt.weekday
        _DAYS_ES = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
        df["weekday"] = df["weekday_num"].map(lambda x: _DAYS_ES[x])
    return df


# ── Sidebar ───────────────────────────────────────────────────────────────────

def _sidebar(accounts: list[dict]):
    with st.sidebar:
        st.markdown("### Filtros")

        today = date.today()
        col1, col2 = st.columns(2)
        date_from = col1.date_input("Desde", value=date(2020, 1, 1), max_value=today)
        date_to = col2.date_input("Hasta", value=today, max_value=today)

        # Group accounts by bank name
        bank_names = sorted({a["bank_name"] for a in accounts})
        selected_banks = st.multiselect("Cuentas", options=bank_names, default=bank_names)
        selected_ids = [a["id"] for a in accounts if a["bank_name"] in selected_banks] or None

        include_cancelled = st.checkbox("Incluir canceladas", value=False)

        st.markdown("---")
        if st.button("Recargar datos", use_container_width=True):
            _load_transactions.clear()
            st.rerun()

        return date_from, date_to, selected_ids, include_cancelled


# ── Tab: Resumen ──────────────────────────────────────────────────────────────

def _tab_resumen(df: pd.DataFrame, accounts: list[dict]) -> None:
    if df.empty:
        st.info("Sin transacciones para el periodo seleccionado.")
        return

    debits = df[df["direction"] == "debit"]
    # Card payments (abonos) vs actual income — semantically different
    card_payments = df[df["credit_type"] == "pago_tarjeta"]
    reembolsos = df[df["credit_type"] == "reembolso"]
    ingresos_reales = df[df["credit_type"] == "ingreso"]

    tagged = df[df["tag_source"] != "pending"]
    expense = debits[debits["primary_tag"] != "sin etiqueta"]

    total_cargos = debits["amount"].sum()
    total_abonos = card_payments["amount"].sum()
    # Net balance change for the period: cargos - abonos
    # Positive = your card balance increased (you owe more)
    # Negative = you paid down more than you charged
    saldo_delta = total_cargos - total_abonos
    avg_monthly = debits.groupby("month")["amount"].sum().mean() if not debits.empty else 0
    pct_tagged = len(tagged) / len(df) * 100 if len(df) else 0
    top_merchant = (
        debits.groupby("merchant")["amount"].sum().idxmax()
        if not debits.empty else "—"
    )

    # ── KPI row ──────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total cargos", _cop(total_cargos, compact=True),
              help="Suma de todos los cargos/compras cobrados a la tarjeta")
    k2.metric("Total abonos", _cop(total_abonos, compact=True),
              help="Pagos que hiciste a la tarjeta (ABONO WOMPI/PSE, debito automatico, etc.)")
    k3.metric(
        "Saldo acumulado",
        _cop(saldo_delta, compact=True),
        delta=f"{'saldo aumentó' if saldo_delta > 0 else 'saldo disminuyó'}",
        delta_color="inverse",
        help="Cargos − Abonos. Positivo = deuda creció. Negativo = pagaste más de lo que cargaste.",
    )
    k4.metric("Promedio mensual", _cop(avg_monthly, compact=True),
              help="Gasto promedio por mes en el periodo filtrado")
    k5.metric("Categorizadas", f"{pct_tagged:.0f}%", delta=f"{len(tagged)}/{len(df)} txns")
    k6.metric("Top comercio", top_merchant[:20] if isinstance(top_merchant, str) else "—")

    # Reembolsos / ingresos info strip
    if not reembolsos.empty or not ingresos_reales.empty:
        info_parts = []
        if not reembolsos.empty:
            info_parts.append(
                f"**{len(reembolsos)} reembolso(s)** de comercios: {_cop(reembolsos['amount'].sum(), compact=True)}"
            )
        if not ingresos_reales.empty:
            info_parts.append(
                f"**{len(ingresos_reales)} ingreso(s) real(es)**: {_cop(ingresos_reales['amount'].sum(), compact=True)}"
            )
        st.info("  |  ".join(info_parts))

    st.markdown("---")

    # ── Monthly cargos vs abonos ──────────────────────────────────────────────
    col_left, col_right = st.columns([2, 1])
    with col_left:
        monthly_d = debits.groupby("month_dt")["amount"].sum().reset_index(name="Cargos")
        monthly_c = card_payments.groupby("month_dt")["amount"].sum().reset_index(name="Abonos")
        monthly = monthly_d.merge(monthly_c, on="month_dt", how="outer").fillna(0).sort_values("month_dt")
        monthly["mes"] = monthly["month_dt"].dt.strftime("%b %Y")

        fig = go.Figure()
        fig.add_bar(x=monthly["mes"], y=monthly["Abonos"], name="Abonos a tarjeta", marker_color="#42A5F5")
        fig.add_bar(x=monthly["mes"], y=monthly["Cargos"], name="Cargos / gastos", marker_color="#EF5350")
        fig.update_layout(
            barmode="group", title="Cargos vs abonos por mes", height=320,
            xaxis_title="", yaxis_title="COP",
            legend=dict(orientation="h", y=1.12),
            margin=dict(t=50, b=30),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_right:
        # Spending by parent category (donut)
        cat_totals = (
            expense.groupby("parent_display")["amount"].sum()
            .reset_index(name="total")
            .sort_values("total", ascending=False)
            .head(8)
        )
        if not cat_totals.empty:
            fig_d = px.pie(
                cat_totals, values="total", names="parent_display",
                title="Gasto por categoria", hole=0.5,
                color_discrete_sequence=px.colors.qualitative.Set2,
            )
            fig_d.update_traces(textposition="inside", textinfo="percent")
            fig_d.update_layout(height=320, showlegend=True,
                                legend=dict(orientation="v", x=1, y=0.5),
                                margin=dict(t=50, b=0, l=0, r=80))
            st.plotly_chart(fig_d, use_container_width=True)

    st.markdown("---")

    # ── Per-account summary ───────────────────────────────────────────────────
    st.markdown("#### Por cuenta")
    id_to_bank = {a["id"]: a["bank_name"] for a in accounts}
    acc_summary = []
    for acc_id, grp in df.groupby("account_id"):
        d = grp[grp["direction"] == "debit"]["amount"].sum()
        c = grp[grp["direction"] == "credit"]["amount"].sum()
        acc_summary.append({
            "Banco": id_to_bank.get(acc_id, str(acc_id)),
            "Txns": len(grp),
            "Gasto": _cop(d, compact=True),
            "Ingresos": _cop(c, compact=True),
            "Desde": grp["date"].min().strftime("%d/%m/%Y"),
            "Hasta": grp["date"].max().strftime("%d/%m/%Y"),
        })
    acc_df = pd.DataFrame(acc_summary).sort_values("Txns", ascending=False)
    st.dataframe(acc_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Recent transactions ───────────────────────────────────────────────────
    st.markdown("#### Ultimas 15 transacciones")
    recent = df.sort_values("date", ascending=False).head(15)
    _TIPO = {"debit": "Cargo", "pago_tarjeta": "Abono", "reembolso": "Reembolso", "ingreso": "Ingreso"}
    display = recent[["date", "direction", "credit_type", "amount", "merchant", "primary_display", "tag_source"]].copy()
    display["Monto"] = display.apply(
        lambda r: _cop(r["amount"]) if r["direction"] == "debit" else f"+{_cop(r['amount'])}",
        axis=1
    )
    display["Tipo"] = display.apply(
        lambda r: _TIPO.get(r["credit_type"] or "debit", "Cargo") if r["direction"] == "credit"
        else "Cargo",
        axis=1
    )
    display["Fecha"] = display["date"].dt.strftime("%d/%m/%Y")
    display = display.rename(columns={
        "merchant": "Comercio", "primary_display": "Categoria", "tag_source": "Fuente"
    })
    st.dataframe(
        display[["Fecha", "Tipo", "Monto", "Comercio", "Categoria", "Fuente"]],
        use_container_width=True, hide_index=True
    )


# ── Tab: Categorías ───────────────────────────────────────────────────────────

def _tab_categorias(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Sin transacciones para el periodo seleccionado.")
        return

    debits = df[df["direction"] == "debit"].copy()
    expense = debits[debits["tag_source"] != "pending"].copy()

    if expense.empty:
        st.info("Sin transacciones categorizadas.")
        return

    # ── Summary row ──────────────────────────────────────────────────────────
    tag_totals = (
        expense.groupby(["primary_tag", "primary_display"])["amount"]
        .agg(total="sum", count="count")
        .reset_index()
        .sort_values("total", ascending=False)
    )
    top_cat = tag_totals.iloc[0]["primary_display"] if not tag_totals.empty else "—"
    top_amount = tag_totals.iloc[0]["total"] if not tag_totals.empty else 0
    unique_cats = len(tag_totals)
    avg_per_cat = tag_totals["total"].mean() if not tag_totals.empty else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Categorias con gasto", str(unique_cats))
    k2.metric("Top categoria", top_cat[:22])
    k3.metric("Gasto top categoria", _cop(top_amount, compact=True))
    k4.metric("Promedio por categoria", _cop(avg_per_cat, compact=True))

    st.markdown("---")

    # ── Pie + bar ─────────────────────────────────────────────────────────────
    col1, col2 = st.columns([1, 1])
    with col1:
        fig_pie = px.pie(
            tag_totals.head(10),
            values="total", names="primary_display",
            title="Distribucion del gasto",
            color_discrete_sequence=px.colors.qualitative.Set3,
            hole=0.4,
        )
        fig_pie.update_traces(textposition="inside", textinfo="percent+label")
        fig_pie.update_layout(height=420, showlegend=False, margin=dict(t=50, b=0))
        st.plotly_chart(fig_pie, use_container_width=True)

    with col2:
        top_bar = tag_totals.head(12).sort_values("total")
        fig_bar = px.bar(
            top_bar, x="total", y="primary_display", orientation="h",
            title="Gasto por categoria",
            color="total", color_continuous_scale="Reds",
            text="count",
            labels={"total": "COP", "primary_display": ""},
        )
        fig_bar.update_traces(texttemplate="%{text} txns", textposition="outside")
        fig_bar.update_layout(height=420, coloraxis_showscale=False, margin=dict(t=50, b=0, r=80))
        st.plotly_chart(fig_bar, use_container_width=True)

    # ── Monthly evolution by category (stacked bar) ───────────────────────────
    st.markdown("---")
    st.markdown("#### Evolucion mensual por categoria")

    top_cats = tag_totals.head(8)["primary_tag"].tolist()
    monthly_cat = (
        expense[expense["primary_tag"].isin(top_cats)]
        .groupby(["month", "primary_display"])["amount"].sum()
        .reset_index()
        .sort_values("month")
    )
    if not monthly_cat.empty:
        fig_stack = px.bar(
            monthly_cat, x="month", y="amount", color="primary_display",
            title="Gasto mensual por categoria (top 8)",
            labels={"month": "Mes", "amount": "COP", "primary_display": "Categoria"},
            color_discrete_sequence=px.colors.qualitative.Set3,
        )
        fig_stack.update_layout(height=350, xaxis_title="", barmode="stack",
                                legend=dict(orientation="h", y=-0.25))
        st.plotly_chart(fig_stack, use_container_width=True)

    # ── Category table ────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Tabla completa")
    table = tag_totals.copy()
    table["Gasto"] = table["total"].apply(_cop)
    table["Promedio"] = (table["total"] / table["count"]).apply(_cop)
    table = table.rename(columns={"primary_display": "Categoria", "count": "Txns"})
    st.dataframe(
        table[["Categoria", "Txns", "Gasto", "Promedio"]],
        use_container_width=True, hide_index=True
    )


# ── Tab: Comercios ────────────────────────────────────────────────────────────

def _tab_comercios(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Sin transacciones para el periodo seleccionado.")
        return

    debits = df[df["direction"] == "debit"].copy()
    if debits.empty:
        st.info("Sin gastos en el periodo seleccionado.")
        return

    merchant_stats = (
        debits.groupby("merchant")
        .agg(total=("amount", "sum"), count=("amount", "count"), avg=("amount", "mean"))
        .reset_index()
        .sort_values("total", ascending=False)
    )

    # ── Summary metrics ───────────────────────────────────────────────────────
    total_merchants = len(merchant_stats)
    top3 = merchant_stats.head(3)["merchant"].tolist()
    single_visit = (merchant_stats["count"] == 1).sum()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Comercios distintos", str(total_merchants))
    k2.metric("Top 1 gasto", top3[0][:22] if top3 else "—")
    k3.metric("Visita unica", str(single_visit), help="Comercios visitados solo 1 vez")
    k4.metric("Ticket promedio global", _cop(debits["amount"].mean(), compact=True))

    st.markdown("---")

    # ── Top merchants chart ───────────────────────────────────────────────────
    col_slider, _ = st.columns([1, 3])
    top_n = col_slider.slider("Mostrar top N", 5, 30, 15, step=5)

    top = merchant_stats.head(top_n).copy()
    top["avg_fmt"] = top["avg"].apply(lambda x: _cop(x, compact=True))
    top_chart = top.sort_values("total")

    col_bar, col_scatter = st.columns([3, 2])
    with col_bar:
        fig = px.bar(
            top_chart, x="total", y="merchant", orientation="h",
            title=f"Top {top_n} comercios por gasto total",
            color="total", color_continuous_scale="Oranges",
            text="count",
            labels={"total": "Total COP", "merchant": ""},
        )
        fig.update_traces(texttemplate="%{text}x", textposition="outside")
        fig.update_layout(
            height=max(380, top_n * 28), coloraxis_showscale=False,
            margin=dict(r=60, t=50)
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_scatter:
        fig_sc = px.scatter(
            merchant_stats.head(40),
            x="count", y="avg",
            size="total", color="total",
            hover_name="merchant",
            title="Frecuencia vs Ticket promedio",
            labels={"count": "Visitas", "avg": "Ticket promedio COP"},
            color_continuous_scale="Oranges",
        )
        fig_sc.update_layout(height=380, coloraxis_showscale=False, margin=dict(t=50))
        st.plotly_chart(fig_sc, use_container_width=True)

    # ── Full table ────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Tabla completa de comercios")
    table = merchant_stats.copy()
    table["Total"] = table["total"].apply(_cop)
    table["Promedio"] = table["avg"].apply(_cop)
    table = table.rename(columns={"merchant": "Comercio", "count": "Visitas"})
    st.dataframe(
        table[["Comercio", "Visitas", "Total", "Promedio"]],
        use_container_width=True, hide_index=True, height=400
    )


# ── Tab: Tendencias ───────────────────────────────────────────────────────────

def _tab_tendencias(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Sin transacciones para el periodo seleccionado.")
        return

    debits = df[df["direction"] == "debit"].copy()
    expense = debits[debits["tag_source"] != "pending"].copy()

    st.markdown("#### Evolucion de categorias en el tiempo")

    tag_totals = (
        expense.groupby("primary_tag")["amount"].sum()
        .sort_values(ascending=False)
    )
    top_tags = tag_totals.head(8).index.tolist()
    top_tags_display = [_display(t) for t in top_tags]

    col_sel, _ = st.columns([2, 3])
    selected_displays = col_sel.multiselect(
        "Categorias a comparar",
        options=[_display(t) for t in top_tags],
        default=top_tags_display[:5],
    )
    selected_tags = [t for t in top_tags if _display(t) in selected_displays]

    if selected_tags:
        monthly_trend = (
            expense[expense["primary_tag"].isin(selected_tags)]
            .groupby(["month_dt", "primary_display"])["amount"].sum()
            .reset_index()
            .sort_values("month_dt")
        )
        if not monthly_trend.empty:
            monthly_trend["mes"] = monthly_trend["month_dt"].dt.strftime("%b %Y")
            fig = px.line(
                monthly_trend, x="mes", y="amount", color="primary_display",
                markers=True, title="Cargos mensuales por categoria",
                labels={"mes": "Mes", "amount": "COP", "primary_display": "Categoria"},
                color_discrete_sequence=px.colors.qualitative.Set1,
            )
            fig.update_layout(height=380, legend=dict(orientation="h", y=-0.25))
            st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")
    st.markdown("#### Comparativa mes a mes")

    # Last two months comparison
    months = sorted(df["month"].unique())
    if len(months) >= 2:
        col_a, col_b = st.columns(2)
        m_prev = col_a.selectbox("Mes anterior", months[:-1], index=max(0, len(months)-2))
        m_curr = col_b.selectbox("Mes actual", months[1:], index=len(months)-2)

        def _month_cat(m: str) -> pd.DataFrame:
            sub = expense[expense["month"] == m]
            return (
                sub.groupby("primary_display")["amount"]
                .sum().reset_index(name="total")
                .sort_values("total", ascending=False)
            )

        prev_df = _month_cat(m_prev).rename(columns={"total": m_prev})
        curr_df = _month_cat(m_curr).rename(columns={"total": m_curr})
        comp = prev_df.merge(curr_df, on="primary_display", how="outer").fillna(0)
        comp["delta"] = comp[m_curr] - comp[m_prev]
        comp["delta_pct"] = ((comp["delta"] / comp[m_prev].replace(0, float("nan"))) * 100).round(1)
        comp = comp.sort_values(m_curr, ascending=False)

        # Comparison bar
        fig_cmp = go.Figure()
        fig_cmp.add_bar(
            y=comp["primary_display"], x=comp[m_prev],
            name=m_prev, orientation="h", marker_color="#90CAF9"
        )
        fig_cmp.add_bar(
            y=comp["primary_display"], x=comp[m_curr],
            name=m_curr, orientation="h", marker_color="#F44336"
        )
        fig_cmp.update_layout(
            barmode="group", height=400, title="Comparativa por categoria",
            xaxis_title="COP", yaxis_title="",
            legend=dict(orientation="h", y=1.05),
            yaxis={"categoryorder": "total ascending"},
        )
        st.plotly_chart(fig_cmp, use_container_width=True)

        # Delta table
        display_comp = comp.copy()
        display_comp[m_prev] = display_comp[m_prev].apply(_cop)
        display_comp[m_curr] = display_comp[m_curr].apply(_cop)
        display_comp["Variacion"] = comp["delta"].apply(
            lambda x: f"+{_cop(x, compact=True)}" if x > 0 else _cop(x, compact=True)
        )
        display_comp["Variacion %"] = comp["delta_pct"].apply(
            lambda x: f"{x:+.1f}%" if pd.notna(x) else "—"
        )
        display_comp = display_comp.rename(columns={"primary_display": "Categoria"})
        st.dataframe(
            display_comp[["Categoria", m_prev, m_curr, "Variacion", "Variacion %"]],
            use_container_width=True, hide_index=True
        )


# ── Tab: Transacciones ────────────────────────────────────────────────────────

def _tab_transacciones(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Sin transacciones para el periodo seleccionado.")
        return

    # ── Filters ───────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    dir_filter = c1.selectbox("Tipo", ["Todos", "Cargo (debito)", "Abono / pago (credito)"])
    search = c2.text_input("Buscar", placeholder="comercio, descripcion...")
    all_cats = ["Todas"] + sorted(df["primary_display"].unique().tolist())
    cat_filter = c3.selectbox("Categoria", all_cats)
    all_sources = ["Todas"] + sorted(df["tag_source"].unique().tolist())
    src_filter = c4.selectbox("Fuente etiqueta", all_sources)

    filtered = df.copy()
    if dir_filter == "Cargo (debito)":
        filtered = filtered[filtered["direction"] == "debit"]
    elif dir_filter == "Abono / pago (credito)":
        filtered = filtered[filtered["direction"] == "credit"]
    if search:
        mask = (
            filtered["description"].str.contains(search, case=False, na=False)
            | filtered["merchant"].str.contains(search, case=False, na=False)
        )
        filtered = filtered[mask]
    if cat_filter != "Todas":
        filtered = filtered[filtered["primary_display"] == cat_filter]
    if src_filter != "Todas":
        filtered = filtered[filtered["tag_source"] == src_filter]

    filtered = filtered.sort_values("date", ascending=False)

    # ── Mini-KPIs for the filtered set ───────────────────────────────────────
    f_debit = filtered[filtered["direction"] == "debit"]["amount"].sum()
    f_credit = filtered[filtered["direction"] == "credit"]["amount"].sum()
    k1, k2, k3 = st.columns(3)
    k1.metric("Resultados", f"{len(filtered):,} transacciones")
    k2.metric("Cargos filtrados", _cop(f_debit, compact=True))
    k3.metric("Abonos filtrados", _cop(f_credit, compact=True))

    # ── Table ──────────────────────────────────────────────────────────────────
    _TIPO = {
        "debit": "Cargo",
        "pago_tarjeta": "Abono tarjeta",
        "reembolso": "Reembolso",
        "ingreso": "Ingreso",
    }
    display = filtered.copy()
    display["Fecha"] = display["date"].dt.strftime("%d/%m/%Y")
    display["Monto"] = display.apply(
        lambda r: _cop(r["amount"]) if r["direction"] == "debit" else f"+{_cop(r['amount'])}",
        axis=1
    )
    display["Tipo"] = display.apply(
        lambda r: _TIPO.get(r["credit_type"] or "debit", "Cargo") if r["direction"] == "credit"
        else "Cargo",
        axis=1
    )
    display = display.rename(columns={
        "merchant": "Comercio",
        "description": "Descripcion", "primary_display": "Categoria",
        "tag_source": "Fuente"
    })
    st.dataframe(
        display[["Fecha", "Tipo", "Monto", "Comercio", "Descripcion", "Categoria", "Fuente"]],
        use_container_width=True, hide_index=True, height=500,
    )


# ── Tab: Días ─────────────────────────────────────────────────────────────────

def _tab_dias(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Sin transacciones para el periodo seleccionado.")
        return

    debits = df[df["direction"] == "debit"].copy()
    if debits.empty:
        st.info("Sin gastos en el periodo seleccionado.")
        return

    _DAYS_ES = ["Lunes", "Martes", "Miercoles", "Jueves", "Viernes", "Sabado", "Domingo"]
    wd_totals = (
        debits.groupby(["weekday_num", "weekday"])
        .agg(total=("amount", "sum"), count=("amount", "count"), avg=("amount", "mean"))
        .reset_index().sort_values("weekday_num")
    )

    # ── KPIs ──────────────────────────────────────────────────────────────────
    if not wd_totals.empty:
        top_day_row = wd_totals.loc[wd_totals["total"].idxmax()]
        least_day_row = wd_totals.loc[wd_totals["total"].idxmin()]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Dia con mas gasto", top_day_row["weekday"])
        k2.metric("Gasto ese dia", _cop(top_day_row["total"], compact=True))
        k3.metric("Dia con menos gasto", least_day_row["weekday"])
        k4.metric("Fin de semana vs semana",
                  f"{debits[debits['weekday_num'] >= 5]['amount'].sum() / debits['amount'].sum() * 100:.0f}%",
                  help="Porcentaje del gasto total que ocurre en sabado/domingo")

    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        fig_total = px.bar(
            wd_totals, x="weekday", y="total",
            title="Gasto total por dia de la semana",
            color="total", color_continuous_scale="Purples",
            labels={"weekday": "", "total": "COP"},
        )
        fig_total.update_layout(height=340, coloraxis_showscale=False)
        st.plotly_chart(fig_total, use_container_width=True)

    with col2:
        fig_avg = px.bar(
            wd_totals, x="weekday", y="avg",
            title="Ticket promedio por dia",
            color="avg", color_continuous_scale="Blues",
            labels={"weekday": "", "avg": "COP promedio"},
        )
        fig_avg.update_layout(height=340, coloraxis_showscale=False)
        st.plotly_chart(fig_avg, use_container_width=True)

    # ── Heatmap: weekday x month ───────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Mapa de calor: mes x dia de la semana")

    heatmap_df = (
        debits.groupby(["month", "weekday_num", "weekday"])["amount"]
        .sum().reset_index(name="total")
    )
    if not heatmap_df.empty:
        heatmap_pivot = heatmap_df.pivot_table(
            index="weekday_num", columns="month", values="total", aggfunc="sum"
        ).fillna(0)
        heatmap_pivot.index = [_DAYS_ES[i] for i in heatmap_pivot.index]
        months_sorted = sorted(heatmap_pivot.columns.tolist())
        heatmap_pivot = heatmap_pivot[months_sorted]

        fig_heat = px.imshow(
            heatmap_pivot,
            title="Gasto (COP) por dia de la semana y mes",
            color_continuous_scale="RdYlGn_r",
            aspect="auto",
            labels={"color": "COP", "x": "Mes", "y": "Dia"},
        )
        fig_heat.update_layout(height=320, margin=dict(t=50))
        st.plotly_chart(fig_heat, use_container_width=True)

    # ── Table ──────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("#### Resumen por dia")
    tbl = wd_totals.copy()
    tbl["Total"] = tbl["total"].apply(_cop)
    tbl["Promedio por txn"] = tbl["avg"].apply(_cop)
    tbl = tbl.rename(columns={"weekday": "Dia", "count": "Transacciones"})
    st.dataframe(tbl[["Dia", "Transacciones", "Total", "Promedio por txn"]], use_container_width=True, hide_index=True)


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    st.title("💳 Bank Agent Dashboard")

    accounts = _load_accounts()
    if not accounts:
        st.warning("Base de datos vacia. Ejecuta `bank-agent import <ruta>` primero.")
        return

    date_from, date_to, account_ids, include_cancelled = _sidebar(accounts)

    df = _load_transactions(
        date_from=date_from,
        date_to=date_to,
        account_ids=tuple(account_ids) if account_ids else None,
        include_cancelled=include_cancelled,
    )

    # Subheader with date range and count
    if not df.empty:
        date_min = df["date"].min().strftime("%d/%m/%Y")
        date_max = df["date"].max().strftime("%d/%m/%Y")
        st.markdown(f"**{len(df):,} transacciones** · {date_min} – {date_max}")

    tabs = st.tabs(["Resumen", "Categorias", "Comercios", "Tendencias", "Transacciones", "Dias"])
    with tabs[0]:
        _tab_resumen(df, accounts)
    with tabs[1]:
        _tab_categorias(df)
    with tabs[2]:
        _tab_comercios(df)
    with tabs[3]:
        _tab_tendencias(df)
    with tabs[4]:
        _tab_transacciones(df)
    with tabs[5]:
        _tab_dias(df)


if __name__ == "__main__":
    main()
