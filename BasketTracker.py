from datetime import date, datetime, timedelta
import hashlib
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st

# 1. Configuración general de la página
st.set_page_config(
    page_title="BasketTracker Cloud",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)


# 2. Encriptación de contraseñas (SHA-256)
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# 3. Conexión a Neon PostgreSQL con verificación de Secrets
def get_db_connection():
    try:
        if "postgres" not in st.secrets or "url" not in st.secrets["postgres"]:
            st.error(
                "❌ Error de configuración: La clave '[postgres]' o 'url' no existe en Secrets."
            )
            return None
        return psycopg2.connect(st.secrets["postgres"]["url"])
    except Exception as e:
        st.error(f"❌ Error de conexión a Neon PostgreSQL: {e}")
        return None


# 4. Inicialización optimizada
@st.cache_resource
def init_db():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            # Tabla de Usuarios
            cur.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    nombre VARCHAR(100) NOT NULL,
                    password_hash VARCHAR(64) NOT NULL,
                    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            # Tabla de Partidos
            cur.execute("""
                CREATE TABLE IF NOT EXISTS partidos (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                    codigo_partido VARCHAR(50) NOT NULL,
                    fecha DATE NOT NULL,
                    tiempo_ejecucion VARCHAR(30),
                    tarifa NUMERIC(10, 2) DEFAULT 0.00,
                    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            st.error(f"❌ Error al inicializar tablas: {e}")
            return False
    return False


init_db()


# 5. Funciones de Autenticación
def registrar_usuario(username, nombre, password):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            pwd_hash = hash_password(password)
            cur.execute(
                """
                INSERT INTO usuarios (username, nombre, password_hash)
                VALUES (%s, %s, %s);
            """,
                (username.lower().strip(), nombre.strip(), pwd_hash),
            )
            conn.commit()
            cur.close()
            conn.close()
            return True, "✅ Usuario registrado exitosamente. Ya puedes iniciar sesión."
        except psycopg2.IntegrityError:
            return False, "⚠️ El nombre de usuario ya existe."
        except Exception as e:
            return False, f"❌ Error en registro: {e}"
    return False, "❌ Error de conexión a BD."


def autenticar_usuario(username, password):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            pwd_hash = hash_password(password)
            cur.execute(
                """
                SELECT id, username, nombre FROM usuarios
                WHERE username = %s AND password_hash = %s;
            """,
                (username.lower().strip(), pwd_hash),
            )
            user = cur.fetchone()
            cur.close()
            conn.close()
            return user
        except Exception as e:
            st.error(f"Error al autenticar: {e}")
            return None
    return None


# 6. Lógica de Cálculo de Tarifa Escalonada por Quincena
def obtener_rango_quincena(fecha_ref):
    if fecha_ref.day <= 15:
        inicio_q = date(fecha_ref.year, fecha_ref.month, 1)
        fin_q = date(fecha_ref.year, fecha_ref.month, 15)
    else:
        inicio_q = date(fecha_ref.year, fecha_ref.month, 16)
        if fecha_ref.month == 12:
            fin_q = date(fecha_ref.year, 12, 31)
        else:
            fin_q = date(fecha_ref.year, fecha_ref.month + 1, 1) - timedelta(days=1)
    return inicio_q, fin_q


def calcular_tarifa_quincenal(usuario_id, fecha_ref):
    inicio_q, fin_q = obtener_rango_quincena(fecha_ref)
    conn = get_db_connection()
    conteo = 0
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT COUNT(*) FROM partidos 
                WHERE usuario_id = %s AND fecha >= %s AND fecha <= %s;
            """,
                (usuario_id, inicio_q, fin_q),
            )
            conteo = cur.fetchone()[0]
            cur.close()
            conn.close()
        except Exception as e:
            st.error(f"Error al calcular conteo quincenal: {e}")

    siguiente_numero = conteo + 1

    # Aplicación del tabulador
    if siguiente_numero <= 11:
        return 6.00, siguiente_numero
    elif siguiente_numero <= 14:
        return 6.50, siguiente_numero
    elif siguiente_numero <= 29:
        return 7.00, siguiente_numero
    else:
        return 8.00, siguiente_numero


# 7. Funciones CRUD de Partidos
def cargar_partidos(usuario_id):
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    try:
        query = """
            SELECT id, codigo_partido, fecha, tiempo_ejecucion, tarifa, creado_en 
            FROM partidos 
            WHERE usuario_id = %s 
            ORDER BY fecha DESC, id DESC;
        """
        df = pd.read_sql_query(query, conn, params=(usuario_id,))
        conn.close()

        if not df.empty:
            df["tarifa"] = pd.to_numeric(df["tarifa"], errors="coerce").fillna(0.0)
            df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
        return df
    except Exception as e:
        st.error(f"Error al cargar partidos: {e}")
        return pd.DataFrame()


def guardar_partido(usuario_id, codigo, fecha_val, tiempo_val, tarifa_val):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO partidos (usuario_id, codigo_partido, fecha, tiempo_ejecucion, tarifa)
                VALUES (%s, %s, %s, %s, %s);
            """,
                (usuario_id, codigo, fecha_val, tiempo_val, tarifa_val),
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            st.error(f"Error al guardar el partido: {e}")
            return False
    return False


def eliminar_partido(id_partido, usuario_id):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "DELETE FROM partidos WHERE id = %s AND usuario_id = %s;",
                (id_partido, usuario_id),
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            st.error(f"Error al eliminar registro: {e}")
            return False
    return False


# 8. Manejo del Estado de Sesión
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_info" not in st.session_state:
    st.session_state.user_info = None

# =========================================================
# VISTA 1: INICIO DE SESIÓN Y REGISTRO
# =========================================================
if not st.session_state.authenticated:
    st.title("🏀 BasketTracker Cloud")
    st.caption("Sistema de Control Financiero y Registro de Partidos")

    tab_login, tab_registro = st.tabs(
        ["🔑 Iniciar Sesión", "📝 Registrar Usuario"]
    )

    with tab_login:
        st.subheader("Ingreso de Operadores")
        with st.form("form_login"):
            user_input = st.text_input("Usuario")
            pass_input = st.text_input("Contraseña", type="password")
            submit_login = st.form_submit_button(
                "Entrar al Sistema", use_container_width=True
            )

            if submit_login:
                if user_input and pass_input:
                    user_data = autenticar_usuario(user_input, pass_input)
                    if user_data:
                        st.session_state.authenticated = True
                        st.session_state.user_info = user_data
                        st.success(f"Bienvenido/a, {user_data['nombre']}")
                        st.rerun()
                    else:
                        st.error("Usuario o contraseña incorrectos.")
                else:
                    st.warning("Complete todos los campos.")

    with tab_registro:
        st.subheader("Crear Cuenta de Usuario")
        with st.form("form_registro"):
            reg_name = st.text_input("Nombre Completo")
            reg_user = st.text_input("Nombre de Usuario")
            reg_pass1 = st.text_input("Contraseña", type="password")
            reg_pass2 = st.text_input("Confirmar Contraseña", type="password")
            submit_reg = st.form_submit_button(
                "Registrar Cuenta", use_container_width=True
            )

            if submit_reg:
                if not (reg_name and reg_user and reg_pass1 and reg_pass2):
                    st.warning("Todos los campos son obligatorios.")
                elif reg_pass1 != reg_pass2:
                    st.error("Las contraseñas no coinciden.")
                elif len(reg_pass1) < 6:
                    st.error("La contraseña debe tener al menos 6 caracteres.")
                else:
                    exito, msg = registrar_usuario(reg_user, reg_name, reg_pass1)
                    if exito:
                        st.success(msg)
                    else:
                        st.error(msg)

# =========================================================
# VISTA 2: PANEL PRINCIPAL DE TRABAJO
# =========================================================
else:
    user_id = st.session_state.user_info["id"]
    user_name = st.session_state.user_info["nombre"]

    st.sidebar.write(f"👤 **Analista:** {user_name}")
    if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_info = None
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.title("🔍 Filtros de Búsqueda")
    periodo = st.sidebar.radio(
        "Seleccionar Período:",
        ["Esta Quincena", "Hoy", "Esta Semana", "Este Mes", "Mostrar Todos"],
    )

    df_todos = cargar_partidos(user_id)

    if not df_todos.empty:
        today = date.today()

        if periodo == "Hoy":
            df_filtrado = df_todos[df_todos["fecha"] == today]
        elif periodo == "Esta Semana":
            inicio_semana = today - timedelta(days=today.weekday())
            df_filtrado = df_todos[df_todos["fecha"] >= inicio_semana]
        elif periodo == "Esta Quincena":
            inicio_q, fin_q = obtener_rango_quincena(today)
            df_filtrado = df_todos[
                (df_todos["fecha"] >= inicio_q) & (df_todos["fecha"] <= fin_q)
            ]
        elif periodo == "Este Mes":
            inicio_mes = date(today.year, today.month, 1)
            df_filtrado = df_todos[df_todos["fecha"] >= inicio_mes]
        else:
            df_filtrado = df_todos.copy()
    else:
        df_filtrado = pd.DataFrame()

    st.title("🏀 BasketTracker Cloud v1.1.0")
    st.caption(f"Panel de Trabajo | Operador: {user_name}")

    # Calcular sugerencia de tarifa automática para el nuevo partido
    tarifa_sugerida, num_partido_q = calcular_tarifa_quincenal(user_id, date.today())

    st.info(
        f"💡 **Tabulador Quincenal Activo:** Estás por registrar el **Partido #{num_partido_q}** de esta quincena. "
        f"Tarifa calculada: **${tarifa_sugerida:.2f}** "
        f"*(1-11: $6.00 | 12-14: $6.50 | 15-29: $7.00 | 30+: $8.00)*"
    )

    cant_partidos = len(df_filtrado)
    total_cobrar = (
        float(df_filtrado["tarifa"].sum()) if not df_filtrado.empty else 0.00
    )

    col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
    col_kpi1.metric("Juegos Registrados", f"{cant_partidos} partidos")
    col_kpi2.metric("Siguiente Tarifa Automática", f"${tarifa_sugerida:.2f}")
    col_kpi3.metric("Monto Total a Cobrar", f"${total_cobrar:.2f}")

    st.markdown("---")

    # Formulario de Entrada
    st.subheader("➕ Registrar Nuevo Partido")
    with st.form("form_registro_partido", clear_on_submit=True):
        col_f1, col_f2, col_f3, col_f4 = st.columns([2, 2, 2, 2])

        with col_f1:
            codigo_input = st.text_input(
                "ID del Partido (Número/Código)", placeholder="Ej: 1042"
            )
        with col_f2:
            fecha_input = st.date_input("Fecha", value=date.today())
        with col_f3:
            tiempo_input = st.text_input(
                "Tiempo en hacerlo", placeholder="HH:MM:SS (Ej: 00:45:00)"
            )
        with col_f4:
            tarifa_input = st.number_input(
                "Tarifa ($)",
                value=tarifa_sugerida,
                min_value=0.0,
                step=0.50,
                format="%.2f",
            )

        submit_btn = st.form_submit_button(
            "💾 Guardar Partido", use_container_width=True
        )

        if submit_btn:
            if not codigo_input.strip():
                st.warning("⚠️ Debe ingresar el ID o Código del Partido.")
            else:
                if guardar_partido(
                    user_id,
                    codigo_input.strip(),
                    fecha_input,
                    tiempo_input.strip(),
                    tarifa_input,
                ):
                    st.success(f"✅ Partido '{codigo_input}' guardado con éxito (${tarifa_input:.2f}).")
                    st.rerun()

    st.markdown("---")
    st.subheader(f"📋 Registros Filtrados ({periodo})")

    if not df_filtrado.empty:
        df_display = df_filtrado.copy()
        df_display["tarifa_fmt"] = df_display["tarifa"].apply(
            lambda x: f"${float(x):.2f}"
        )

        df_tabla = df_display[[
            "id",
            "codigo_partido",
            "fecha",
            "tiempo_ejecucion",
            "tarifa_fmt",
        ]].copy()
        df_tabla.columns = [
            "ID DB",
            "Código / Partido",
            "Fecha",
            "Tiempo de Ejecución",
            "Tarifa ($)",
        ]

        st.dataframe(df_tabla, use_container_width=True, hide_index=True)

        col_exp1, col_exp2 = st.columns([1, 1])

        # Exportación
        with col_exp1:
            df_export = df_display[[
                "codigo_partido",
                "fecha",
                "tiempo_ejecucion",
                "tarifa",
            ]].copy()
            df_export.columns = [
                "Código Partido",
                "Fecha",
                "Tiempo Ejecución",
                "Tarifa ($)",
            ]
            csv_data = df_export.to_csv(index=False).encode("utf-8")
            filename_periodo = periodo.lower().replace(" ", "_")

            st.download_button(
                label="📥 Exportar Reporte (CSV / Excel)",
                data=csv_data,
                file_name=f"reporte_partidos_{filename_periodo}_{date.today()}.csv",
                mime="text/csv",
                use_container_width=True,
            )

        # Eliminación
        with col_exp2:
            with st.expander("🗑️ Gestionar / Eliminar Registros"):
                opciones_eliminar = {
                    f"ID DB: {row['id']} | Partido: {row['codigo_partido']} ({row['fecha']})": row[
                        "id"
                    ]
                    for _, row in df_filtrado.iterrows()
                }
                partido_sel = st.selectbox(
                    "Seleccione el registro a eliminar:",
                    options=list(opciones_eliminar.keys()),
                )

                if st.button("🔴 Eliminar Registro Seleccionado"):
                    id_a_borrar = opciones_eliminar[partido_sel]
                    if eliminar_partido(id_a_borrar, user_id):
                        st.success("Registro eliminado correctamente.")
                        st.rerun()
    else:
        st.info(f"ℹ No hay partidos registrados en el período: {periodo}")
