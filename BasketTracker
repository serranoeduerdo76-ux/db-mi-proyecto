"""
BasketTracker Cloud — Sistema Web de Control de Partidos de Baloncesto
Versión: 1.0.0
Tecnología: Python + Streamlit + Neon PostgreSQL
"""

import os
import sqlite3
import datetime
import pandas as pd
import streamlit as st

# Configuración de página de Streamlit
st.set_page_config(
    page_title="BasketTracker Cloud",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─────────────────────────────────────────────
# MÓDULO 1: BASE DE DATOS (Soporte Híbrido Neon/SQLite)
# ─────────────────────────────────────────────
def obtener_conexion():
    """
    Intenta conectar a Neon PostgreSQL usando la variable de entorno DATABASE_URL.
    Si no existe o no hay conexión, usa SQLite local como respaldo para pruebas.
    """
    db_url = os.environ.get("DATABASE_URL") or st.secrets.get("DATABASE_URL", None)
    
    if db_url:
        import psycopg2
        return psycopg2.connect(db_url), "postgresql"
    else:
        conn = sqlite3.connect("basket_tracker.db")
        return conn, "sqlite"

def inicializar_bd():
    conn, db_type = obtener_conexion()
    cursor = conn.cursor()
    
    if db_type == "postgresql":
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS partidos (
                id SERIAL PRIMARY KEY,
                id_partido VARCHAR(50) NOT NULL,
                fecha DATE NOT NULL,
                tiempo_ejecucion VARCHAR(20) NOT NULL,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
    else:
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS partidos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                id_partido TEXT NOT NULL,
                fecha TEXT NOT NULL,
                tiempo_ejecucion TEXT NOT NULL,
                creado_en DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        ''')
    
    conn.commit()
    conn.close()

def guardar_partido(id_partido, fecha, tiempo):
    conn, db_type = obtener_conexion()
    cursor = conn.cursor()
    
    if db_type == "postgresql":
        cursor.execute('''
            INSERT INTO partidos (id_partido, fecha, tiempo_ejecucion)
            VALUES (%s, %s, %s)
        ''', (id_partido, fecha, tiempo))
    else:
        cursor.execute('''
            INSERT INTO partidos (id_partido, fecha, tiempo_ejecucion)
            VALUES (?, ?, ?)
        ''', (id_partido, str(fecha), tiempo))
        
    conn.commit()
    conn.close()

def eliminar_partido(id_reg):
    conn, db_type = obtener_conexion()
    cursor = conn.cursor()
    
    if db_type == "postgresql":
        cursor.execute("DELETE FROM partidos WHERE id = %s", (id_reg,))
    else:
        cursor.execute("DELETE FROM partidos WHERE id = ?", (id_reg,))
        
    conn.commit()
    conn.close()

# ─────────────────────────────────────────────
# MÓDULO 2: LÓGICA DE NEGOCIO (TARIFAS)
# ─────────────────────────────────────────────
def calcular_tarifa_unitaria(cantidad_juegos):
    if cantidad_juegos < 1:
        return 0.0
    elif 1 <= cantidad_juegos <= 11:
        return 6.0
    elif 12 <= cantidad_juegos <= 14:
        return 6.5
    elif 15 <= cantidad_juegos <= 29:
        return 7.0
    else:
        return 8.0

# ─────────────────────────────────────────────
# MÓDULO 3: INTERFAZ WEB CON STREAMLIT
# ─────────────────────────────────────────────
inicializar_bd()

# Encabezado
st.title("🏀 BasketTracker Cloud v1.0.0")
st.caption("Sistema Web de Gestión de Partidos y Control Financiero Quincenal")

# ── BARRA LATERAL (Filtros Temporales) ──
st.sidebar.header("🔍 Filtros de Búsqueda")
filtro_periodo = st.sidebar.radio(
    "Seleccionar Periodo:",
    ["Esta Quincena", "Hoy", "Esta Semana", "Este Mes", "Mostrar Todos"]
)

# Determinación de rango de fechas
hoy = datetime.date.today()
f_inicio, f_fin = None, None

if filtro_periodo == "Hoy":
    f_inicio = f_fin = hoy
elif filtro_periodo == "Esta Semana":
    f_inicio = hoy - datetime.timedelta(days=hoy.weekday())
    f_fin = hoy + datetime.timedelta(days=6 - hoy.weekday())
elif filtro_periodo == "Esta Quincena":
    if hoy.day <= 15:
        f_inicio = hoy.replace(day=1)
        f_fin = hoy.replace(day=15)
    else:
        f_inicio = hoy.replace(day=16)
        # Último día del mes actual
        siguiente_mes = hoy.replace(day=28) + datetime.timedelta(days=4)
        f_fin = siguiente_mes.replace(day=1) - datetime.timedelta(days=1)
elif filtro_periodo == "Este Mes":
    f_inicio = hoy.replace(day=1)
    siguiente_mes = hoy.replace(day=28) + datetime.timedelta(days=4)
    f_fin = siguiente_mes.replace(day=1) - datetime.timedelta(days=1)

# Consulta de datos según filtro
conn, db_type = obtener_conexion()

if f_inicio and f_fin:
    query = "SELECT id, id_partido, fecha, tiempo_ejecucion FROM partidos WHERE fecha BETWEEN %s AND %s ORDER BY id DESC" if db_type == "postgresql" else "SELECT id, id_partido, fecha, tiempo_ejecucion FROM partidos WHERE fecha BETWEEN ? AND ? ORDER BY id DESC"
    df = pd.read_sql_query(query, conn, params=(str(f_inicio), str(f_fin)))
else:
    query = "SELECT id, id_partido, fecha, tiempo_ejecucion FROM partidos ORDER BY id DESC"
    df = pd.read_sql_query(query, conn)

conn.close()

# ── MÉTRICAS SUPERIORES ──
cant_juegos = len(df)
tarifa_u = calcular_tarifa_unitaria(cant_juegos)
monto_total = cant_juegos * tarifa_u

col1, col2, col3 = st.columns(3)
col1.metric("Juegos Registrados", f"{cant_juegos} partidos")
col2.metric("Tarifa Unitaria", f"${tarifa_u:.2f}")
col3.metric("Monto Total a Cobrar", f"${monto_total:.2f}")

st.divider()

# ── FORMULARIO DE REGISTRO ──
st.subheader("➕ Registrar Nuevo Partido")

with st.form("form_partido", clear_on_submit=True):
    col_a, col_b, col_c = st.columns([2, 1, 1])
    
    with col_a:
        id_input = st.text_input("ID del Partido (Número/Código)", placeholder="Ej: 1042")
    with col_b:
        fecha_input = st.date_input("Fecha", value=hoy)
    with col_c:
        tiempo_input = st.text_input("Tiempo en hacerlo", placeholder="HH:MM:SS (Ej: 00:45:00)")
        
    btn_guardar = st.form_submit_button("💾 Guardar Partido", use_container_width=True)

if btn_guardar:
    if not id_input or not tiempo_input:
        st.error("⚠️ Por favor ingrese el ID del Partido y el Tiempo de Ejecución.")
    else:
        guardar_partido(id_input, fecha_input, tiempo_input)
        st.success(f"✅ Partido ID {id_input} guardado correctamente.")
        st.rerun()

st.divider()

# ── TABLA DE RESULTADOS ──
st.subheader(f"📋 Registros Encontrados ({filtro_periodo})")

if not df.empty:
    st.dataframe(
        df.rename(columns={
            "id": "REG #",
            "id_partido": "ID PARTIDO",
            "fecha": "FECHA",
            "tiempo_ejecucion": "TIEMPO EJECUCIÓN"
        }),
        use_container_width=True,
        hide_index=True
    )
    
    # Opción para eliminar
    with st.expander("🗑️ Eliminar un registro"):
        id_eliminar = st.selectbox("Seleccione el REG # a eliminar:", df["id"].tolist())
        if st.button("Confirmar Eliminación", type="primary"):
            eliminar_partido(id_eliminar)
            st.warning(f"Registro REG #{id_eliminar} eliminado.")
            st.rerun()
else:
    st.info("No se encontraron partidos registrados para el periodo seleccionado.")
