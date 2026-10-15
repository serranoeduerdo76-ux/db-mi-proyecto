from datetime import date, datetime, timedelta
import hashlib
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st

# =========================================================
# 1. CONFIGURACIÓN GENERAL DE LA PÁGINA
# =========================================================
st.set_page_config(
    page_title="BasketTracker Cloud",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)


# =========================================================
# 2. SEGURIDAD Y ENCRIPTACIÓN DE CONTRASEÑAS (SHA-256)
# =========================================================
def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


# =========================================================
# 3. CONEXIÓN A BASE DE DATOS (NEON POSTGRESQL)
# =========================================================
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


# =========================================================
# 4. INICIALIZACIÓN DE TABLAS Y CONFIGURACIÓN GLOBAL
# =========================================================
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
            # Tabla de Configuración Global (Tasas de pago por tramo)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS configuracion_global (
                    clave VARCHAR(50) PRIMARY KEY,
                    valor NUMERIC(10, 2) NOT NULL
                );
            """)
            # Valores por defecto de tasas de pago
            default_tasa = [
                ("tasa_tramo_1", 6.00),
                ("tasa_tramo_2", 6.50),
                ("tasa_tramo_3", 7.00),
                ("tasa_tramo_4", 8.00),
            ]
            for clave, val in default_tasa:
                cur.execute(
                    """
                    INSERT INTO configuracion_global (clave, valor) 
                    VALUES (%s, %s) 
                    ON CONFLICT (clave) DO NOTHING;
                """,
                    (clave, val),
                )

            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            st.error(f"❌ Error al inicializar tablas: {e}")
            return False
    return False


init_db()


# =========================================================
# 5. FUNCIONES DE CONFIGURACIÓN Y TARIFAS DINÁMICAS
# =========================================================
def obtener_tasas_globales():
    conn = get_db_connection()
    tasas = {
        "tramo_1": 6.00,
        "tramo_2": 6.50,
        "tramo_3": 7.00,
        "tramo_4": 8.00,
    }
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT clave, valor FROM configuracion_global;")
            rows = cur.fetchall()
            for r in rows:
                if r["clave"] == "tasa_tramo_1":
                    tasas["tramo_1"] = float(r["valor"])
                elif r["clave"] == "tasa_tramo_2":
                    tasas["tramo_2"] = float(r["valor"])
                elif r["clave"] == "tasa_tramo_3":
                    tasas["tramo_3"] = float(r["valor"])
                elif r["clave"] == "tasa_tramo_4":
                    tasas["tramo_4"] = float(r["valor"])
            cur.close()
            conn.close()
        except Exception:
            pass
    return tasas


def actualizar_tasa_global(clave, nuevo_valor):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE configuracion_global SET valor = %s WHERE clave = %s;
            """,
                (nuevo_valor, clave),
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            st.error(f"Error al actualizar tasa: {e}")
            return False
    return False


def obtener_tarifa_unitaria(cant_partidos):
    tasas = obtener_tasas_globales()
    if cant_partidos <= 11:
        return tasas["tramo_1"]
    elif cant_partidos <= 14:
        return tasas["tramo_2"]
    elif cant_partidos <= 29:
        return tasas["tramo_3"]
    else:
        return tasas["tramo_4"]


# =========================================================
# 6. FUNCIONES AUXILIARES Y GESTIÓN DE USUARIOS
# =========================================================
def sumar_tiempos(lista_tiempos):
    total_segundos = 0
    for t in lista_tiempos:
        if not t or not isinstance(t, str):
            continue
        partes = t.strip().split(":")
        try:
            if len(partes) == 3:
                h, m, s = map(int, partes)
                total_segundos += h * 3600 + m * 60 + s
            elif len(partes) == 2:
                m, s = map(int, partes)
                total_segundos += m * 60 + s
            elif len(partes) == 1 and partes[0].isdigit():
                total_segundos += int(partes[0]) * 60
        except ValueError:
            continue
    return total_segundos


def formatear_segundos(total_segundos):
    horas = total_segundos // 3600
    minutos = (total_segundos % 3600) // 60
    segundos = total_segundos % 60
    return f"{horas:02d}h {minutos:02d}m {segundos:02d}s"


def calcular_monto_quincenal_blindado(cant_partidos):
    tarifa_uni = obtener_tarifa_unitaria(cant_partidos)
    total_monto = float(cant_partidos) * float(tarifa_uni)
    return total_monto, tarifa_uni


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
            return True, "✅ Usuario registrado exitosamente."
        except psycopg2.IntegrityError:
            return False, "⚠️ El nombre de usuario ya existe."
        except Exception as e:
            return False, f"❌ Error en registro: {e}"
    return False, "❌ Error de conexión a BD."


def cambiar_password_usuario(usuario_id, nueva_password):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            pwd_hash = hash_password(nueva_password)
            cur.execute(
                """
                UPDATE usuarios SET password_hash = %s WHERE id = %s;
            """,
                (pwd_hash, usuario_id),
            )
            conn.commit()
            cur.close()
            conn.close()
            return True, "✅ Contraseña modificada exitosamente."
        except Exception as e:
            return False, f"❌ Error al cambiar contraseña: {e}"
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


def obtener_todos_los_usuarios():
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    try:
        query = """
            SELECT u.id, u.username, u.nombre, u.creado_en,
                   COUNT(p.id) as total_partidos
            FROM usuarios u
            LEFT JOIN partidos p ON u.id = p.usuario_id
            GROUP BY u.id, u.username, u.nombre, u.creado_en
            ORDER BY u.id ASC;
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error al cargar usuarios: {e}")
        return pd.DataFrame()


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


def obtener_conteo_quincena_por_fecha(usuario_id, fecha_ref):
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
        except Exception:
            pass
    return conteo


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
            df["tiempo_ejecucion"] = df["tiempo_ejecucion"].fillna("00:00:00")
        return df
    except Exception:
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
        except Exception:
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
        except Exception:
            return False
    return False


# =========================================================
# 7. MANEJO DE SESIÓN Y VISTAS
# =========================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_info" not in st.session_state:
    st.session_state.user_info = None

# VISTA 1: LOGIN / REGISTRO
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

# VISTA 2: PANEL PRINCIPAL Y MÓDULO DE ADMINISTRACIÓN
else:
    user_id = st.session_state.user_info["id"]
    user_name = st.session_state.user_info["nombre"]
    username_actual = st.session_state.user_info["username"].lower().strip()

    # =========================================================
    # REGLA ADMIN v2.7.0: Se considera Admin el usuario 'admin', id 1, 
    # o puedes agregar aquí tu propio nombre de usuario (ej. 'eduardo')
    # =========================================================
    es_admin = (username_actual == "admin") or (user_id == 1) or (username_actual in ["admin", "eduardorene", "eduardorene300"])

    st.sidebar.write(f"👤 **Analista:** {user_name}")
    if es_admin:
        st.sidebar.markdown("👑 **Rol:** Administrador Global")
    else:
        st.sidebar.markdown("🟢 **Rol:** Operador Estándar")

    if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_info = None
        st.rerun()

    st.sidebar.markdown("---")
    
    # Menú de navegación lateral si es admin
    if es_admin:
        modo_vista = st.sidebar.radio(
            "🧭 Menú de Navegación:",
            ["📊 Mi Panel de Partidos", "👑 Panel de Administración Global"]
        )
    else:
        modo_vista = "📊 Mi Panel de Partidos"

    # =========================================================
    # VISTA: PANEL DE ADMINISTRACIÓN GLOBAL (SOLO ADMIN)
    # =========================================================
    if es_admin and modo_vista == "👑 Panel de Administración Global":
        st.title("👑 Panel de Administración Global (v2.7.0)")
        st.caption("Gestión general de usuarios, contraseñas y tabla de precios por partidos")

        tab_admin_tasas, tab_admin_usuarios, tab_admin_pass = st.tabs(
            ["⚙️ Tabla de Precios por Partidos", "➕ Registrar Nuevo Usuario", "🔑 Modificar Contraseña de Usuario"]
        )

        # TAB 1: MODIFICACIÓN DE LA TABLA DE PRECIOS GLOBALES
        with tab_admin_tasas:
            st.subheader("⚙️ Modificar Tabla de Precios por Partidos (Tramos)")
            st.caption("Define el valor unitario por partido según el volumen alcanzado en la quincena para todos los operadores.")
            
            tasas_actuales = obtener_tasas_globales()

            with st.form("form_tasas_globales"):
                col_t1, col_t2, col_t3, col_t4 = st.columns(4)
                with col_t1:
                    nuevo_t1 = st.number_input("Tramo 1 (1 - 11 Juegos)", value=tasas_actuales["tramo_1"], step=0.25, format="%.2f")
                with col_t2:
                    nuevo_t2 = st.number_input("Tramo 2 (12 - 14 Juegos)", value=tasas_actuales["tramo_2"], step=0.25, format="%.2f")
                with col_t3:
                    nuevo_t3 = st.number_input("Tramo 3 (15 - 29 Juegos)", value=tasas_actuales["tramo_3"], step=0.25, format="%.2f")
                with col_t4:
                    nuevo_t4 = st.number_input("Tramo 4 (30+ Juegos)", value=tasas_actuales["tramo_4"], step=0.25, format="%.2f")

                guardar_tasas_btn = st.form_submit_button("💾 Guardar Nueva Tabla de Precios", use_container_width=True)
                if guardar_tasas_btn:
                    actualizar_tasa_global("tasa_tramo_1", nuevo_t1)
                    actualizar_tasa_global("tasa_tramo_2", nuevo_t2)
                    actualizar_tasa_global("tasa_tramo_3", nuevo_t3)
                    actualizar_tasa_global("tasa_tramo_4", nuevo_t4)
                    st.success("✅ ¡Tabla de precios actualizada con éxito para todo el sistema!")
                    st.rerun()

        # TAB 2: REGISTRO DE NUEVOS USUARIOS DESDE EL PANEL DE ADMIN
        with tab_admin_usuarios:
            st.subheader("➕ Registrar Nuevo Usuario Operador")
            with st.form("form_admin_crear_usuario"):
                col_u1, col_u2 = st.columns(2)
                with col_u1:
                    adm_reg_name = st.text_input("Nombre Completo del Usuario")
                    adm_reg_user = st.text_input("Nombre de Usuario (Username)")
                with col_u2:
                    adm_reg_pass1 = st.text_input("Contraseña Inicial", type="password")
                    adm_reg_pass2 = st.text_input("Confirmar Contraseña Inicial", type="password")

                btn_crear_usr = st.form_submit_button("👤 Crear Usuario Operador", use_container_width=True)
                if btn_crear_usr:
                    if not (adm_reg_name and adm_reg_user and adm_reg_pass1 and adm_reg_pass2):
                        st.warning("⚠️ Todos los campos son obligatorios.")
                    elif adm_reg_pass1 != adm_reg_pass2:
                        st.error("❌ Las contraseñas no coinciden.")
                    elif len(adm_reg_pass1) < 6:
                        st.error("❌ La contraseña debe tener al menos 6 caracteres.")
                    else:
                        exito_creacion, msg_creacion = registrar_usuario(adm_reg_user, adm_reg_name, adm_reg_pass1)
                        if exito_creacion:
                            st.success(msg_creacion)
                            st.rerun()
                        else:
                            st.error(msg_creacion)

        # TAB 3: MODIFICACIÓN / CAMBIO DE CONTRASEÑA DE CUALQUIER USUARIO
        with tab_admin_pass:
            st.subheader("🔑 Cambiar / Restablecer Contraseña de Usuario")
            df_usuarios_list = obtener_todos_los_usuarios()

            if not df_usuarios_list.empty:
                dict_usuarios = {
                    f"ID: {row['id']} | Usuario: {row['username']} ({row['nombre']})": row["id"]
                    for _, row in df_usuarios_list.iterrows()
                }

                with st.form("form_admin_cambiar_pass"):
                    usuario_seleccionado_str = st.selectbox(
                        "Selecciona el usuario al que deseas cambiarle la contraseña:",
                        options=list(dict_usuarios.keys())
                    )
                    pass_nueva1 = st.text_input("Nueva Contraseña", type="password")
                    pass_nueva2 = st.text_input("Confirmar Nueva Contraseña", type="password")

                    btn_cambiar_pass = st.form_submit_button("🔑 Actualizar Contraseña del Usuario", use_container_width=True)

                    if btn_cambiar_pass:
                        id_usr_destino = dict_usuarios[usuario_seleccionado_str]
                        if not (pass_nueva1 and pass_nueva2):
                            st.warning("⚠️ Ingresa la nueva contraseña.")
                        elif pass_nueva1 != pass_nueva2:
                            st.error("❌ Las contraseñas no coinciden.")
                        elif len(pass_nueva1) < 6:
                            st.error("❌ La contraseña debe tener al menos 6 caracteres.")
                        else:
                            exito_chg, msg_chg = cambiar_password_usuario(id_usr_destino, pass_nueva1)
                            if exito_chg:
                                st.success(msg_chg)
                            else:
                                st.error(msg_chg)
            else:
                st.info("No hay usuarios registrados para cambiar contraseña.")

        st.markdown("---")
        st.subheader("👥 Listado General de Usuarios Registrados")
        df_usuarios = obtener_todos_los_usuarios()

        if not df_usuarios.empty:
            df_usuarios_display = df_usuarios.copy()
            df_usuarios_display.columns = [
                "ID",
                "Nombre de Usuario",
                "Nombre Completo",
                "Fecha de Registro",
                "Total Partidos Cargados",
            ]
            st.dataframe(df_usuarios_display, use_container_width=True, hide_index=True)

    # =========================================================
    # VISTA: PANEL DE PARTIDOS (OPERADOR / PERSONAL)
    # =========================================================
    else:
        st.sidebar.markdown("---")
        st.sidebar.title("🔍 Filtros de Búsqueda")
        periodo = st.sidebar.radio(
            "Seleccionar Período:",
            ["Esta Quincena", "Hoy", "Esta Semana", "Este Mes", "Mostrar Todos"],
        )

        df_todos = cargar_partidos(user_id)

        if not df_todos.empty:
            today = date.today()
            fecha_ref_historica = df_todos["fecha"].max()

            if periodo == "Hoy":
                df_filtrado = df_todos[df_todos["fecha"] == today]
            elif periodo == "Esta Semana":
                inicio_semana = today - timedelta(days=today.weekday())
                df_filtrado = df_todos[df_todos["fecha"] >= inicio_semana]
            elif periodo == "Esta Quincena":
                inicio_q, fin_q = obtener_rango_quincena(fecha_ref_historica)
                df_filtrado = df_todos[
                    (df_todos["fecha"] >= inicio_q) & (df_todos["fecha"] <= fin_q)
                ]
            elif periodo == "Este Mes":
                inicio_mes = date(fecha_ref_historica.year, fecha_ref_historica.month, 1)
                df_filtrado = df_todos[df_todos["fecha"] >= inicio_mes]
            else:
                df_filtrado = df_todos.copy()
        else:
            df_filtrado = pd.DataFrame()
            fecha_ref_historica = date.today()

        st.title("🏀 BasketTracker Cloud v2.7.0")
        st.caption(f"Panel de Trabajo | Operador: {user_name}")

        # Formulario de registro de partidos
        st.subheader("➕ Registrar Nuevo Partido")
        
        col_f_fecha, col_f_id, col_f_tiempo = st.columns([2, 2, 2])
        with col_f_fecha:
            fecha_input = st.date_input("Fecha del Partido", value=date.today())
        with col_f_id:
            codigo_input = st.text_input("ID / Código del Partido", placeholder="Ej: 1042")
        with col_f_tiempo:
            tiempo_input = st.text_input("Tiempo de Ejecución", placeholder="HH:MM:SS (Ej: 02:20:00)")

        conteo_quincena_form = obtener_conteo_quincena_por_fecha(user_id, fecha_input)
        siguiente_numero = conteo_quincena_form + 1
        tarifa_sugerida = obtener_tarifa_unitaria(siguiente_numero)

        st.info(
            f"💡 **Tabulador Quincenal Dinámico (v2.7.0):** Para la fecha seleccionada ({fecha_input}), "
            f"registrarás el **Partido #{siguiente_numero}** de su quincena. "
            f"Tarifa unitaria sugerida: **${tarifa_sugerida:.2f}**"
        )

        if st.button("💾 Guardar Partido en la Base de Datos", use_container_width=True):
            if not codigo_input.strip():
                st.warning("⚠️ Debe ingresar el ID o Código del Partido.")
            else:
                if guardar_partido(
                    user_id,
                    codigo_input.strip(),
                    fecha_input,
                    tiempo_input.strip(),
                    tarifa_sugerida,
                ):
                    st.success(f"✅ Partido '{codigo_input}' guardado con éxito.")
                    st.rerun()

        st.markdown("---")

        # ---------------------------------------------------------
        # MÉTRICAS Y TOTALES
        # ---------------------------------------------------------
        cant_partidos = len(df_filtrado)

        if periodo == "Esta Quincena" and not df_filtrado.empty:
            total_cobrar, tarifa_vigente_lote = calcular_monto_quincenal_blindado(cant_partidos)
        else:
            total_cobrar = float(df_filtrado["tarifa"].sum()) if not df_filtrado.empty else 0.00

        total_segundos = (
            sumar_tiempos(df_filtrado["tiempo_ejecucion"].tolist())
            if not df_filtrado.empty
            else 0
        )
        tiempo_total_str = formatear_segundos(total_segundos)

        if cant_partidos > 0:
            promedio_segundos = total_segundos // cant_partidos
        else:
            promedio_segundos = 0
        promedio_tiempo_str = formatear_segundos(promedio_segundos)

        col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
        col_kpi1.metric("🏀 Partidos", f"{cant_partidos} juegos")
        col_kpi2.metric("⏱️ Tiempo Total", tiempo_total_str)
        col_kpi3.metric("📊 Promedio / Juego", promedio_tiempo_str)
        col_kpi4.metric("💵 Total Quincena", f"${total_cobrar:.2f}")

        st.markdown("---")
        st.subheader(f"📋 Registros Filtrados ({periodo})")

        if not df_filtrado.empty:
            df_display = df_filtrado.copy()
            
            if periodo == "Esta Quincena":
                tarifa_actual_lote = obtener_tarifa_unitaria(len(df_display))
                df_display["tarifa_efectiva"] = tarifa_actual_lote
            else:
                df_display["tarifa_efectiva"] = df_display["tarifa"]

            df_display["tarifa_fmt"] = df_display["tarifa_efectiva"].apply(
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
                "Tarifa Unitaria ($)",
            ]

            st.dataframe(df_tabla, use_container_width=True, hide_index=True)

            col_exp1, col_exp2 = st.columns([1, 1])

            with col_exp1:
                df_export = df_display[[
                    "codigo_partido",
                    "fecha",
                    "tiempo_ejecucion",
                    "tarifa_efectiva",
                ]].copy()
                df_export.columns = [
                    "Código Partido",
                    "Fecha",
                    "Tiempo Ejecución",
                    "Tarifa Unitaria ($)",
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
            st.info(f"ℹ️ No hay partidos registrados en el período: {periodo}")
