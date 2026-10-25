from datetime import date, datetime, timedelta
import hashlib
import pandas as pd
import psycopg2
from psycopg2.extras import RealDictCursor
import streamlit as st

# =========================================================
# 1. CONFIGURACIÓN GENERAL
# =========================================================
st.set_page_config(
    page_title="BasketTracker Cloud",
    page_icon="🏀",
    layout="wide",
    initial_sidebar_state="expanded",
)

BUILD_HASH = "v2.15-BOTON-VISIBLE"


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_db_connection():
    try:
        if "postgres" not in st.secrets or "url" not in st.secrets["postgres"]:
            st.error("❌ Falta '[postgres]' o 'url' en Secrets.")
            return None
        return psycopg2.connect(st.secrets["postgres"]["url"])
    except Exception as e:
        st.error(f"❌ Error de conexión a Neon: {e}")
        return None


@st.cache_resource
def init_db():
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(50) UNIQUE NOT NULL,
                    nombre VARCHAR(100) NOT NULL,
                    password_hash VARCHAR(64) NOT NULL,
                    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS partidos (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE CASCADE,
                    codigo_partido VARCHAR(50) NOT NULL,
                    fecha DATE NOT NULL,
                    tiempo_ejecucion VARCHAR(30),
                    tarifa NUMERIC(10, 2) DEFAULT 0.00,
                    tipo_partido VARCHAR(30) DEFAULT 'quincenal',
                    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            cur.execute("""
                DO $$ 
                BEGIN 
                    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='partidos' AND column_name='tipo_partido') THEN
                        ALTER TABLE partidos ADD COLUMN tipo_partido VARCHAR(30) DEFAULT 'quincenal';
                    END IF;
                END $$;
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS configuracion_global (
                    clave VARCHAR(50) PRIMARY KEY,
                    valor NUMERIC(10, 2) NOT NULL
                );
            """)
            for clave, val in [
                ("tasa_tramo_1", 6.00), ("tasa_tramo_2", 6.50),
                ("tasa_tramo_3", 7.00), ("tasa_tramo_4", 7.50),
                ("tasa_tramo_5", 8.00), ("tasa_en_vivo_normal", 12.00),
                ("tasa_en_vivo_nba", 18.50),
            ]:
                cur.execute(
                    "INSERT INTO configuracion_global (clave, valor) VALUES (%s, %s) ON CONFLICT (clave) DO NOTHING;",
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
# 5. TASAS Y TARIFAS
# =========================================================
def obtener_tasas_globales():
    conn = get_db_connection()
    tasas = {
        "tramo_1": 6.00, "tramo_2": 6.50, "tramo_3": 7.00,
        "tramo_4": 7.50, "tramo_5": 8.00,
        "en_vivo_normal": 12.00, "en_vivo_nba": 18.50,
    }
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute("SELECT clave, valor FROM configuracion_global;")
            for r in cur.fetchall():
                mapa = {
                    "tasa_tramo_1": "tramo_1", "tasa_tramo_2": "tramo_2",
                    "tasa_tramo_3": "tramo_3", "tasa_tramo_4": "tramo_4",
                    "tasa_tramo_5": "tramo_5", "tasa_en_vivo_normal": "en_vivo_normal",
                    "tasa_en_vivo_nba": "en_vivo_nba",
                }
                if r["clave"] in mapa:
                    tasas[mapa[r["clave"]]] = float(r["valor"])
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
            cur.execute("UPDATE configuracion_global SET valor = %s WHERE clave = %s;", (nuevo_valor, clave))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception as e:
            st.error(f"Error al actualizar tasa: {e}")
            return False
    return False


def obtener_tarifa_unitaria(tipo_partido, cant_partidos=0):
    t = obtener_tasas_globales()
    if tipo_partido == "en_vivo_nba":
        return t["en_vivo_nba"]
    if tipo_partido == "en_vivo_normal":
        return t["en_vivo_normal"]
    if cant_partidos <= 11:
        return t["tramo_1"]
    if cant_partidos <= 14:
        return t["tramo_2"]
    if cant_partidos <= 26:
        return t["tramo_3"]
    if cant_partidos <= 29:
        return t["tramo_4"]
    return t["tramo_5"]


# =========================================================
# 6. AUXILIARES
# =========================================================
def normalizar_formato_tiempo(tiempo_str):
    if not tiempo_str or not isinstance(tiempo_str, str):
        return "00:00:00"
    t = tiempo_str.strip()
    if ":" in t:
        return t
    if t.isdigit():
        t = t.zfill(6)
        if len(t) == 6:
            return f"{t[:2]}:{t[2:4]}:{t[4:6]}"
    return t


def sumar_tiempos(lista_tiempos):
    total = 0
    for t in lista_tiempos:
        if not t or not isinstance(t, str):
            continue
        tn = normalizar_formato_tiempo(t)
        if not tn or tn.lower() in ["nan", "nat", "none", "--"]:
            continue
        p = tn.split(":")
        try:
            if len(p) == 3:
                h, m, s = map(int, p)
                total += h * 3600 + m * 60 + s
            elif len(p) == 2:
                m, s = map(int, p)
                total += m * 60 + s
            elif len(p) == 1 and p[0].isdigit():
                total += int(p[0]) * 60
        except ValueError:
            continue
    return total


def formatear_segundos(total_segundos):
    if total_segundos < 0:
        total_segundos = 0
    h = total_segundos // 3600
    m = (total_segundos % 3600) // 60
    s = total_segundos % 60
    return f"{h:02d}h {m:02d}m {s:02d}s"


def registrar_usuario(username, nombre, password):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO usuarios (username, nombre, password_hash) VALUES (%s, %s, %s);",
                (username.lower().strip(), nombre.strip(), hash_password(password)),
            )
            conn.commit()
            cur.close()
            conn.close()
            return True, "✅ Usuario registrado exitosamente."
        except psycopg2.IntegrityError:
            return False, "⚠️ El nombre de usuario ya existe."
        except Exception as e:
            return False, f"❌ Error: {e}"
    return False, "❌ Error de conexión a BD."


def cambiar_password_usuario(usuario_id, nueva_password):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute("UPDATE usuarios SET password_hash = %s WHERE id = %s;",
                        (hash_password(nueva_password), usuario_id))
            conn.commit()
            cur.close()
            conn.close()
            return True, "✅ Contraseña modificada."
        except Exception as e:
            return False, f"❌ Error: {e}"
    return False, "❌ Error de conexión a BD."


def autenticar_usuario(username, password):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(
                "SELECT id, username, nombre FROM usuarios WHERE username = %s AND password_hash = %s;",
                (username.lower().strip(), hash_password(password)),
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
            SELECT u.id, u.username, u.nombre, u.creado_en, COUNT(p.id) as total_partidos
            FROM usuarios u LEFT JOIN partidos p ON u.id = p.usuario_id
            GROUP BY u.id, u.username, u.nombre, u.creado_en ORDER BY u.id ASC;
        """
        df = pd.read_sql_query(query, conn)
        conn.close()
        return df
    except Exception as e:
        st.error(f"Error al cargar usuarios: {e}")
        return pd.DataFrame()


def obtener_rango_quincena(fecha_ref):
    if fecha_ref.day <= 15:
        return date(fecha_ref.year, fecha_ref.month, 1), date(fecha_ref.year, fecha_ref.month, 15)
    inicio = date(fecha_ref.year, fecha_ref.month, 16)
    fin = date(fecha_ref.year, 12, 31) if fecha_ref.month == 12 else date(fecha_ref.year, fecha_ref.month + 1, 1) - timedelta(days=1)
    return inicio, fin


def obtener_conteo_quincena_por_fecha(usuario_id, fecha_ref):
    inicio_q, fin_q = obtener_rango_quincena(fecha_ref)
    conn = get_db_connection()
    conteo = 0
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM partidos WHERE usuario_id = %s AND fecha >= %s AND fecha <= %s AND (tipo_partido IS NULL OR tipo_partido = 'quincenal');",
                (usuario_id, inicio_q, fin_q),
            )
            conteo = cur.fetchone()[0]
            cur.close()
            conn.close()
        except Exception:
            pass
    return conteo


def recalcular_tarifas_usuario(usuario_id):
    conn = get_db_connection()
    if not conn:
        return False
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            "SELECT id, fecha, tipo_partido FROM partidos WHERE usuario_id = %s ORDER BY fecha ASC, id ASC;",
            (usuario_id,),
        )
        partidos = cur.fetchall()
        conteo = {}
        for p in partidos:
            tipo = p["tipo_partido"] or "quincenal"
            if tipo != "quincenal":
                continue
            f = p["fecha"]
            if not hasattr(f, "day"):
                continue
            qk = (f.year, f.month, 1) if f.day <= 15 else (f.year, f.month, 2)
            conteo[qk] = conteo.get(qk, 0) + 1
        cur_upd = conn.cursor()
        for p in partidos:
            tipo = p["tipo_partido"] or "quincenal"
            if tipo == "quincenal":
                f = p["fecha"]
                qk = (f.year, f.month, 1) if f.day <= 15 else (f.year, f.month, 2)
                tarifa = obtener_tarifa_unitaria("quincenal", conteo.get(qk, 0))
            else:
                tarifa = obtener_tarifa_unitaria(tipo, 0)
            cur_upd.execute("UPDATE partidos SET tarifa = %s WHERE id = %s;", (tarifa, p["id"]))
        cur_upd.close()
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        st.error(f"Error al recalcular: {e}")
        return False


def verificar_y_autocorregir_tarifas(usuario_id, df_partidos):
    if df_partidos is None or df_partidos.empty:
        return False, df_partidos
    df_std = df_partidos[df_partidos["tipo_partido"] == "quincenal"].copy()
    if df_std.empty:
        return False, df_partidos
    df_std["q_key"] = df_std["fecha"].apply(
        lambda f: (f.year, f.month, 1) if f.day <= 15 else (f.year, f.month, 2)
    )
    conteo_q = df_std.groupby("q_key").size().to_dict()
    tasas = obtener_tasas_globales()

    def tarifa_esperada(qk):
        n = conteo_q.get(qk, 0)
        if n <= 11: return tasas["tramo_1"]
        if n <= 14: return tasas["tramo_2"]
        if n <= 26: return tasas["tramo_3"]
        if n <= 29: return tasas["tramo_4"]
        return tasas["tramo_5"]

    df_std["esperada"] = df_std["q_key"].apply(tarifa_esperada)
    df_std["actual"] = df_std["tarifa"].astype(float)
    if int((df_std["actual"].round(2) != df_std["esperada"].round(2)).sum()) > 0:
        ok = recalcular_tarifas_usuario(usuario_id)
        return ok, cargar_partidos(usuario_id)
    return False, df_partidos


def cargar_partidos(usuario_id):
    conn = get_db_connection()
    if not conn:
        return pd.DataFrame()
    try:
        query = """
            SELECT id, codigo_partido, fecha, tiempo_ejecucion, tarifa, tipo_partido, creado_en
            FROM partidos WHERE usuario_id = %s ORDER BY fecha ASC, id ASC;
        """
        df = pd.read_sql_query(query, conn, params=(usuario_id,))
        conn.close()
        if not df.empty:
            df["tarifa"] = pd.to_numeric(df["tarifa"], errors="coerce").fillna(0.0)
            df["fecha"] = pd.to_datetime(df["fecha"]).dt.date
            df["tiempo_ejecucion"] = df["tiempo_ejecucion"].fillna("00:00:00").astype(str)
            df["tipo_partido"] = df["tipo_partido"].fillna("quincenal")
        return df
    except Exception:
        return pd.DataFrame()


def guardar_partido(usuario_id, codigo, fecha_val, tiempo_val, tarifa_val, tipo_partido):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO partidos (usuario_id, codigo_partido, fecha, tiempo_ejecucion, tarifa, tipo_partido) VALUES (%s, %s, %s, %s, %s, %s);",
                (usuario_id, codigo, fecha_val, normalizar_formato_tiempo(tiempo_val), tarifa_val, tipo_partido),
            )
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception:
            return False
    return False


def actualizar_partido(id_partido, usuario_id, codigo, fecha_val, tiempo_val, tarifa_val, tipo_partido):
    conn = get_db_connection()
    if conn:
        try:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE partidos SET codigo_partido = %s, fecha = %s, tiempo_ejecucion = %s,
                    tarifa = %s, tipo_partido = %s
                WHERE id = %s AND usuario_id = %s;
                """,
                (codigo, fecha_val, normalizar_formato_tiempo(tiempo_val), tarifa_val, tipo_partido, id_partido, usuario_id),
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
            cur.execute("DELETE FROM partidos WHERE id = %s AND usuario_id = %s;", (id_partido, usuario_id))
            conn.commit()
            cur.close()
            conn.close()
            return True
        except Exception:
            return False
    return False


# =========================================================
# 7. SECCIÓN REUTILIZABLE: CORREGIR / ELIMINAR
# =========================================================
def render_seccion_corregir_eliminar(user_id, key_suffix=""):
    with st.container(border=True):
        st.markdown("### ✏️ Corregir / 🗑️ Eliminar Partido Existente")
        st.caption("Solo se modifica el partido seleccionado. Después se reajustan las tarifas de la quincena si el total cruza un tramo.")

        df_edit = cargar_partidos(user_id)

        if df_edit.empty:
            st.info("No hay partidos registrados para corregir o eliminar.")
            return

        st.success(f"✅ Cargados **{len(df_edit)}** partidos. Selecciona uno para editar o eliminar.")

        opciones = {
            f"#{row['id']} | {row['codigo_partido']} | {row['fecha']} | {row['tipo_partido']} | ${float(row['tarifa']):.2f}": row["id"]
            for _, row in df_edit.iterrows()
        }

        seleccion = st.selectbox(
            "Selecciona el partido:",
            options=list(opciones.keys()),
            key=f"sel_partido_editar{key_suffix}",
        )
        id_sel = opciones[seleccion]
        fila = df_edit[df_edit["id"] == id_sel].iloc[0]

        tipo_map = {
            "🏀 Quincenal Estándar": "quincenal",
            "⚡ En Vivo Normal": "en_vivo_normal",
            "🔥 En Vivo NBA": "en_vivo_nba",
        }
        tipos_validos = list(tipo_map.values())
        tipo_actual = fila["tipo_partido"] if fila["tipo_partido"] in tipos_validos else "quincenal"
        idx_tipo = tipos_validos.index(tipo_actual)

        with st.form(f"form_editar_partido{key_suffix}"):
            col1, col2 = st.columns(2)
            with col1:
                edit_codigo = st.text_input("Código del Partido", value=str(fila["codigo_partido"]))
                edit_fecha = st.date_input("Fecha", value=fila["fecha"])
            with col2:
                edit_tiempo = st.text_input("Tiempo de Ejecución", value=str(fila["tiempo_ejecucion"]))
                edit_tipo_label = st.selectbox("Modalidad", list(tipo_map.keys()), index=idx_tipo)
                edit_tipo = tipo_map[edit_tipo_label]

            confirmar = st.checkbox("✔️ Confirmo que quiero eliminar este partido (marca esto y pulsa Eliminar).")

            b1, b2 = st.columns(2)
            with b1:
                btn_guardar = st.form_submit_button("💾 Guardar Corrección", use_container_width=True)
            with b2:
                btn_eliminar = st.form_submit_button("🗑️ Eliminar Partido", use_container_width=True)

            if btn_guardar:
                if actualizar_partido(id_sel, user_id, edit_codigo.strip(), edit_fecha,
                                      edit_tiempo.strip(), float(fila["tarifa"]), edit_tipo):
                    recalcular_tarifas_usuario(user_id)
                    st.success(f"✅ Partido #{id_sel} corregido y tarifas reajustadas.")
                    st.rerun()
                else:
                    st.error("❌ No se pudo actualizar.")

            if btn_eliminar:
                if not confirmar:
                    st.warning("⚠️ Marca la casilla de confirmación para eliminar.")
                elif eliminar_partido(id_sel, user_id):
                    recalcular_tarifas_usuario(user_id)
                    st.success(f"✅ Partido #{id_sel} eliminado y tarifas reajustadas.")
                    st.rerun()
                else:
                    st.error("❌ No se pudo eliminar.")


# =========================================================
# 8. SESIÓN Y VISTAS
# =========================================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_info" not in st.session_state:
    st.session_state.user_info = None

if not st.session_state.authenticated:
    st.title("🏀 BasketTracker Cloud")
    st.caption("Sistema de Control Financiero y Registro de Partidos")
    st.sidebar.caption(f"🧾 Build: `{BUILD_HASH}`")

    tab_login, tab_registro = st.tabs(["🔑 Iniciar Sesión", "📝 Registrar Usuario"])

    with tab_login:
        st.subheader("Ingreso de Operadores")
        with st.form("form_login"):
            user_input = st.text_input("Usuario")
            pass_input = st.text_input("Contraseña", type="password")
            if st.form_submit_button("Entrar al Sistema", use_container_width=True):
                if user_input and pass_input:
                    user_data = autenticar_usuario(user_input, pass_input)
                    if user_data:
                        st.session_state.authenticated = True
                        st.session_state.user_info = user_data
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
            if st.form_submit_button("Registrar Cuenta", use_container_width=True):
                if not (reg_name and reg_user and reg_pass1 and reg_pass2):
                    st.warning("Todos los campos son obligatorios.")
                elif reg_pass1 != reg_pass2:
                    st.error("Las contraseñas no coinciden.")
                elif len(reg_pass1) < 6:
                    st.error("La contraseña debe tener al menos 6 caracteres.")
                else:
                    exito, msg = registrar_usuario(reg_user, reg_name, reg_pass1)
                    (st.success if exito else st.error)(msg)

else:
    user_id = st.session_state.user_info["id"]
    user_name = st.session_state.user_info["nombre"]
    username_actual = st.session_state.user_info["username"].lower().strip()
    es_admin = (username_actual == "geremo01")

    st.sidebar.write(f"👤 **Analista:** {user_name}")
    st.sidebar.caption(f"ID: {user_id} | Username: {username_actual}")
    st.sidebar.caption(f"🧾 Build: `{BUILD_HASH}`")

    if es_admin:
        st.sidebar.markdown("👑 **Rol:** Administrador Global")
    else:
        st.sidebar.markdown("🟢 **Rol:** Operador Estándar")

    if st.sidebar.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_info = None
        st.rerun()

    st.sidebar.markdown("---")

    if es_admin:
        modo_vista = st.sidebar.radio(
            "🧭 Menú de Navegación:",
            ["📊 Mi Panel de Partidos", "👑 Panel de Administración Global"],
        )
    else:
        modo_vista = "📊 Mi Panel de Partidos"

    # ---------- ADMIN ----------
    if es_admin and modo_vista == "👑 Panel de Administración Global":
        st.title("👑 Panel de Administración Global (v2.15)")
        st.caption("Gestión de usuarios, contraseñas, tabla de precios y MIS partidos")

        tab1, tab2, tab3, tab4 = st.tabs([
            "⚙️ Tabla de Precios",
            "➕ Registrar Usuario",
            "🔑 Modificar Contraseña",
            "✏️ Mis Partidos (Corregir/Eliminar)",
        ])

        with tab1:
            st.subheader("⚙️ Modificar Tabla de Precios")
            tasas = obtener_tasas_globales()
            with st.form("form_tasas"):
                st.markdown("##### 📌 Tramos Quincenales (Estándar, retroactivos)")
                c1, c2, c3, c4, c5 = st.columns(5)
                with c1: t1 = st.number_input("Tramo 1 (1-11)", value=tasas["tramo_1"], step=0.25, format="%.2f")
                with c2: t2 = st.number_input("Tramo 2 (12-14)", value=tasas["tramo_2"], step=0.25, format="%.2f")
                with c3: t3 = st.number_input("Tramo 3 (15-26)", value=tasas["tramo_3"], step=0.25, format="%.2f")
                with c4: t4 = st.number_input("Tramo 4 (27-29)", value=tasas["tramo_4"], step=0.25, format="%.2f")
                with c5: t5 = st.number_input("Tramo 5 (30+)", value=tasas["tramo_5"], step=0.25, format="%.2f")

                st.markdown("##### ⚡ En Vivo")
                cv1, cv2 = st.columns(2)
                with cv1: vn = st.number_input("En Vivo Normal ($)", value=tasas["en_vivo_normal"], step=0.50, format="%.2f")
                with cv2: vb = st.number_input("En Vivo NBA ($)", value=tasas["en_vivo_nba"], step=0.50, format="%.2f")

                if st.form_submit_button("💾 Guardar Tabla de Precios", use_container_width=True):
                    actualizar_tasa_global("tasa_tramo_1", t1)
                    actualizar_tasa_global("tasa_tramo_2", t2)
                    actualizar_tasa_global("tasa_tramo_3", t3)
                    actualizar_tasa_global("tasa_tramo_4", t4)
                    actualizar_tasa_global("tasa_tramo_5", t5)
                    actualizar_tasa_global("tasa_en_vivo_normal", vn)
                    actualizar_tasa_global("tasa_en_vivo_nba", vb)
                    st.success("✅ Tabla actualizada.")
                    st.rerun()

        with tab2:
            st.subheader("➕ Registrar Nuevo Usuario")
            with st.form("form_crear_usr"):
                u1, u2 = st.columns(2)
                with u1:
                    n = st.text_input("Nombre Completo")
                    usr = st.text_input("Username")
                with u2:
                    p1 = st.text_input("Contraseña", type="password")
                    p2 = st.text_input("Confirmar", type="password")
                if st.form_submit_button("👤 Crear Usuario", use_container_width=True):
                    if not (n and usr and p1 and p2):
                        st.warning("Todos los campos son obligatorios.")
                    elif p1 != p2:
                        st.error("Las contraseñas no coinciden.")
                    elif len(p1) < 6:
                        st.error("Mínimo 6 caracteres.")
                    else:
                        exito, msg = registrar_usuario(usr, n, p1)
                        if exito:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

        with tab3:
            st.subheader("🔑 Cambiar Contraseña")
            df_u = obtener_todos_los_usuarios()
            if not df_u.empty:
                opciones = {f"ID:{r['id']} | {r['username']} ({r['nombre']})": r["id"] for _, r in df_u.iterrows()}
                with st.form("form_cambiar_pwd"):
                    sel = st.selectbox("Usuario:", list(opciones.keys()))
                    np1 = st.text_input("Nueva Contraseña", type="password")
                    np2 = st.text_input("Confirmar", type="password")
                    if st.form_submit_button("🔑 Actualizar", use_container_width=True):
                        if not (np1 and np2):
                            st.warning("Ingresa la nueva contraseña.")
                        elif np1 != np2:
                            st.error("Las contraseñas no coinciden.")
                        elif len(np1) < 6:
                            st.error("Mínimo 6 caracteres.")
                        else:
                            exito, msg = cambiar_password_usuario(opciones[sel], np1)
                            if exito:
                                st.success(msg)
                            else:
                                st.error(msg)
            else:
                st.info("No hay usuarios registrados.")

        with tab4:
            st.markdown("#### ✏️ Corregir / 🗑️ Eliminar MIS Partidos")
            render_seccion_corregir_eliminar(user_id, key_suffix="_admin")

        st.markdown("---")
        st.subheader("👥 Listado General de Usuarios")
        df_users = obtener_todos_los_usuarios()
        if not df_users.empty:
            disp = df_users.copy()
            disp.columns = ["ID", "Username", "Nombre Completo", "Fecha Registro", "Total Partidos"]
            st.dataframe(disp, use_container_width=True, hide_index=True)

    # ---------- OPERADOR ----------
    else:
        st.sidebar.markdown("---")
        st.sidebar.title("🔍 Filtros de Búsqueda")
        periodo = st.sidebar.radio(
            "Seleccionar Período:",
            ["Mostrar Todos", "Hoy", "Esta Semana", "1ª Quincena (1 al 15)", "2ª Quincena (16 al Fin de Mes)", "Este Mes"],
        )

        mes_filtro = datetime.now().month
        ano_filtro = datetime.now().year
        if "Quincena" in periodo:
            st.sidebar.markdown("---")
            st.sidebar.subheader("📅 Selector de Mes")
            ano_filtro = st.sidebar.selectbox("Año", [2025, 2026, 2027], index=1)
            mes_nombres = {
                1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
                5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
                9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
            }
            sel_mes_str = st.sidebar.selectbox("Mes", list(mes_nombres.values()), index=datetime.now().month - 1)
            mes_filtro = [k for k, v in mes_nombres.items() if v == sel_mes_str][0]

        df_todos = cargar_partidos(user_id)
        hubo_corr, df_todos = verificar_y_autocorregir_tarifas(user_id, df_todos)
        if hubo_corr:
            st.toast("🔧 Tarifas autocorregidas (regla retroactiva).", icon="✅")

        if not df_todos.empty:
            today = date.today()
            if periodo == "Hoy":
                df_f = df_todos[df_todos["fecha"] == today]
            elif periodo == "Esta Semana":
                ini = today - timedelta(days=today.weekday())
                df_f = df_todos[df_todos["fecha"] >= ini]
            elif periodo == "1ª Quincena (1 al 15)":
                df_f = df_todos[(df_todos["fecha"] >= date(ano_filtro, mes_filtro, 1)) &
                                (df_todos["fecha"] <= date(ano_filtro, mes_filtro, 15))]
            elif periodo == "2ª Quincena (16 al Fin de Mes)":
                fi = date(ano_filtro, 12, 31) if mes_filtro == 12 else date(ano_filtro, mes_filtro + 1, 1) - timedelta(days=1)
                df_f = df_todos[(df_todos["fecha"] >= date(ano_filtro, mes_filtro, 16)) & (df_todos["fecha"] <= fi)]
            elif periodo == "Este Mes":
                df_f = df_todos[df_todos["fecha"] >= date(today.year, today.month, 1)]
            else:
                df_f = df_todos.copy()
        else:
            df_f = pd.DataFrame()

        st.title("🏀 BasketTracker Cloud v2.15")
        st.caption(f"Panel de Trabajo | Operador: {user_name}")

        # ---- KPIs arriba ----
        cant = len(df_f)
        total_cobrar = float(df_f["tarifa"].sum()) if not df_f.empty else 0.0
        total_seg = sumar_tiempos(df_f["tiempo_ejecucion"].tolist()) if not df_f.empty else 0
        prom_seg = total_seg // cant if cant > 0 else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🏀 Partidos", f"{cant} juegos")
        c2.metric("⏱️ Tiempo Total", formatear_segundos(total_seg))
        c3.metric("📊 Promedio / Juego", formatear_segundos(prom_seg))
        c4.metric("💵 Total Ganancias", f"${total_cobrar:.2f}")

        st.markdown("---")

        if st.button("🔄 Forzar Recálculo de Tarifas en Base de Datos", use_container_width=True):
            if recalcular_tarifas_usuario(user_id):
                st.success("¡Tarifas recalculadas!")
                st.rerun()
            else:
                st.error("Error al recalcular.")

        # ---- Registrar nuevo partido ----
        st.subheader("➕ Registrar Nuevo Partido")
        col_m, _ = st.columns([2, 2])
        with col_m:
            modalidad = st.radio(
                "Tipo / Modalidad:",
                ["🏀 Quincenal Estándar (Tabulador)", "⚡ En Vivo Normal", "🔥 En Vivo NBA"],
                horizontal=False,
            )

        cf1, cf2, cf3 = st.columns(3)
        with cf1: fecha_input = st.date_input("Fecha del Partido", value=date.today())
        with cf2: codigo_input = st.text_input("Código del Partido", placeholder="Ej: 1042")
        with cf3: tiempo_input = st.text_input("Tiempo de Ejecución", placeholder="HH:MM:SS")

        tasas_v = obtener_tasas_globales()
        if "En Vivo NBA" in modalidad:
            tipo_guardar = "en_vivo_nba"
            tarifa_sug = tasas_v["en_vivo_nba"]
            st.info(f"🔥 **En Vivo NBA:** ${tarifa_sug:.2f}")
        elif "En Vivo Normal" in modalidad:
            tipo_guardar = "en_vivo_normal"
            tarifa_sug = tasas_v["en_vivo_normal"]
            st.info(f"⚡ **En Vivo Normal:** ${tarifa_sug:.2f}")
        else:
            tipo_guardar = "quincenal"
            cnt = obtener_conteo_quincena_por_fecha(user_id, fecha_input)
            sig = cnt + 1
            tarifa_sug = obtener_tarifa_unitaria("quincenal", sig)
            st.info(f"💡 **Partido estándar #{sig} de la quincena** → todos a **${tarifa_sug:.2f}**")

        if st.button("💾 Guardar Partido", use_container_width=True):
            if not codigo_input.strip():
                st.warning("⚠️ Debe ingresar el ID del Partido.")
            elif guardar_partido(user_id, codigo_input.strip(), fecha_input,
                                 tiempo_input.strip(), tarifa_sug, tipo_guardar):
                recalcular_tarifas_usuario(user_id)
                st.success(f"✅ Partido '{codigo_input}' guardado.")
                st.rerun()

        # ---- CORREGIR / ELIMINAR ----
        render_seccion_corregir_eliminar(user_id, key_suffix="_operador")

        # ---- Tabla ----
        st.markdown("---")
        st.subheader(f"📋 Registros Filtrados ({periodo})")

        if not df_f.empty:
            disp = df_f.copy()

            def fmt_tipo(t):
                return {"en_vivo_nba": "🔥 En Vivo NBA",
                        "en_vivo_normal": "⚡ En Vivo Normal"}.get(t, "🏀 Quincenal Estándar")

            disp["Modalidad"] = disp["tipo_partido"].apply(fmt_tipo)
            disp["tiempo_ejecucion"] = disp["tiempo_ejecucion"].apply(normalizar_formato_tiempo)
            disp["tarifa_fmt"] = disp["tarifa"].apply(lambda x: f"${float(x):.2f}")

            tabla = disp[["id", "codigo_partido", "fecha", "Modalidad", "tiempo_ejecucion", "tarifa_fmt"]].copy()
            tabla.columns = ["ID DB", "Código", "Fecha", "Modalidad", "Tiempo", "Tarifa ($)"]
            st.dataframe(tabla, use_container_width=True, hide_index=True)

            df_exp = disp[["codigo_partido", "fecha", "Modalidad", "tiempo_ejecucion", "tarifa"]].copy()
            df_exp.columns = ["Código", "Fecha", "Modalidad", "Tiempo", "Tarifa ($)"]
            st.download_button(
                "📥 Descargar Reporte en CSV",
                data=df_exp.to_csv(index=False).encode("utf-8"),
                file_name="reporte_partidos_basket.csv",
                mime="text/csv",
                use_container_width=True,
            )
