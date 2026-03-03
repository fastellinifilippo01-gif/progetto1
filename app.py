import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json
import time

# --- CONFIGURAZIONE ---
SHEET_NAME = "Scacchi_DB"
K_FACTOR = 32
RATING_INIZIALE = 1500

st.set_page_config(page_title="Federazione Scacchistica", layout="wide", page_icon="♟️")

# --- CONNESSIONE DATABASE ---
@st.cache_resource
def get_gc():
    """Connessione a Google Sheets (cache permanente)"""
    try:
        secrets = st.secrets["google_credentials"]
        credentials_info = json.loads(secrets["json_content"])
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Errore connessione Google: {str(e)}")
        return None

def get_all_data(gc, sheet_name):
    """Legge i dati dai fogli Google (SENZA cache problematica)"""
    try:
        spreadsheet = gc.open(sheet_name)
        data = {}
        for ws_name in ["Giocatori", "Tornei", "Partite"]:
            try:
                worksheet = spreadsheet.worksheet(ws_name)
                data[ws_name] = (pd.DataFrame(worksheet.get_all_records()), worksheet)
            except gspread.exceptions.WorksheetNotFound:
                data[ws_name] = (pd.DataFrame(), None)
        return data
    except Exception as e:
        st.error(f"❌ Errore lettura dati: {str(e)}")
        return {}

def safe_api_call(func, max_retries=3):
    """Esegue una chiamata API con retry in caso di quota exceeded"""
    for attempt in range(max_retries):
        try:
            return func()
        except gspread.exceptions.APIError as e:
            if "429" in str(e) or "Quota exceeded" in str(e):
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    st.warning(f"⏳ Limite API raggiunto. Attendo {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    st.error("❌ Troppe richieste. Riprova tra 1 minuto.")
                    return None
            raise
    return None

# --- FUNZIONI LOGICHE ---
def calculate_elo(rating_a, rating_b, score_a):
    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    new_a = rating_a + K_FACTOR * (score_a - expected_a)
    new_b = rating_b + K_FACTOR * ((1 - score_a) - (1 - expected_a))
    return round(new_a), round(new_b)

def swiss_pairing(players, past_matches):
    players_sorted = sorted(players, key=lambda x: x['Rating'], reverse=True)
    pairings = []
    paired = set()
    for i, p1 in enumerate(players_sorted):
        if p1['Nome'] in paired:
            continue
        for j, p2 in enumerate(players_sorted[i+1:], start=i+1):
            if p2['Nome'] in paired:
                continue
            history = [(m['Giocatore1'], m['Giocatore2']) for m in past_matches]
            if (p1['Nome'], p2['Nome']) in history or (p2['Nome'], p1['Nome']) in history:
                continue
            pairings.append((p1, p2))
            paired.add(p1['Nome'])
            paired.add(p2['Nome'])
            break
    return pairings

# --- GESTIONE SESSIONE ---
if 'admin_logged_in' not in st.session_state:
    st.session_state.admin_logged_in = False

def check_admin():
    if not st.session_state.admin_logged_in:
        st.warning("🔒 Accesso admin richiesto.")
        return False
    return True

def logout():
    st.session_state.admin_logged_in = False
    st.rerun()

# --- INTERFACCIA ---
st.title("♟️ Federazione Scacchistica Amatoriale")

# Inizializza connessione (con cache resource)
gc = get_gc()
if not gc:
    st.stop()

# Carica dati OGNI VOLTA (no cache data per evitare errori hash)
# Per un torneo piccolo (<100 giocatori) è sufficientemente veloce
data = get_all_data(gc, SHEET_NAME)
df_giocatori, ws_giocatori = data.get("Giocatori", (pd.DataFrame(), None))
df_tornei, ws_tornei = data.get("Tornei", (pd.DataFrame(), None))
df_partite, ws_partite = data.get("Partite", (pd.DataFrame(), None))

# Sidebar Menu
menu_options = ["Home", "Classifica", "Tornei", "Iscriviti"]
if st.session_state.admin_logged_in:
    menu_options.append("🛡️ Admin Panel")
else:
    menu_options.append("🔐 Login Admin")
menu = st.sidebar.selectbox("Menu", menu_options)

# --- HOME ---
if menu == "Home":
    st.header("🏠 Benvenuto")
    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Giocatori", len(df_giocatori) if not df_giocatori.empty else 0)
    with col2: st.metric("Tornei", len(df_tornei) if not df_tornei.empty else 0)
    with col3: st.metric("Partite", len(df_partite) if not df_partite.empty else 0)
    st.info(f"📊 Sistema Elo (K={K_FACTOR}) | Rating iniziale: {RATING_INIZIALE}")
    if not df_tornei.empty:
        st.markdown("### 🏆 Ultimi Tornei")
        st.dataframe(df_tornei.tail(5), use_container_width=True)

# --- CLASSIFICA ---
elif menu == "Classifica":
    st.header("🏆 Classifica")
    if not df_giocatori.empty:
        search = st.text_input("🔍 Cerca")
        df_show = df_giocatori[df_giocatori['Nome'].str.contains(search, case=False, na=False)] if search else df_giocatori
        st.dataframe(df_show.sort_values("Rating", ascending=False), use_container_width=True)
    else:
        st.warning("Nessun giocatore.")

# --- TORNEI ---
elif menu == "Tornei":
    st.header("📅 Tornei")
    if not df_tornei.empty:
        filtro = st.selectbox("Stato", ["Tutti", "In Programmazione", "In Corso", "Concluso"])
        df_show = df_tornei[df_tornei['Stato'] == filtro] if filtro != "Tutti" else df_tornei
        st.dataframe(df_show, use_container_width=True)
        if not df_show.empty:
            sel = st.selectbox("Dettagli", df_show['Nome'].tolist())
            t = df_tornei[df_tornei['Nome']==sel].iloc[0]
            st.write(f"**{t['Nome']}** - {t['Data']} - {t['Tipo']} - {t['Stato']}")
            if not df_partite.empty:
                part = df_partite[df_partite['ID_Torneo']==t['ID_Torneo']]
                if not part.empty:
                    st.markdown("##### Risultati")
                    st.dataframe(part, use_container_width=True)
    else:
        st.info("Nessun torneo.")

# --- ISCRIVITI ---
elif menu == "Iscriviti":
    st.header("📝 Iscrizione")
    if not df_tornei.empty:
        aperti = df_tornei[df_tornei['Stato']=="In Programmazione"]
        if not aperti.empty:
            sel = st.selectbox("Torneo", aperti['Nome'].tolist())
            nome = st.text_input("Nome")
            email = st.text_input("Email (opz.)")
            if st.button("Invia"):
                st.success("✅ Iscrizione inviata! Contatta l'admin per confermare.")
        else:
            st.info("Nessun torneo aperto.")
    else:
        st.warning("Nessun torneo disponibile.")

# --- LOGIN ADMIN ---
elif menu == "🔐 Login Admin":
    st.header("🔐 Login")
    pwd = st.text_input("Password", type="password")
    if st.button("Accedi"):
        try:
            if pwd == st.secrets["admin"]["password"]:
                st.session_state.admin_logged_in = True
                st.success("✅ Accesso!")
                st.rerun()
            else:
                st.error("❌ Password errata")
        except:
            st.error("Errore configurazione Secrets")

# --- ADMIN PANEL ---
elif menu == "🛡️ Admin Panel":
    if not check_admin():
        st.stop()
    st.header("🛡️ Admin")
    if st.sidebar.button("🚪 Logout"):
        logout()
    
    tab1, tab2, tab3 = st.tabs(["📝 Crea Torneo", "🎮 Risultati", "👤 Giocatori"])
    
    with tab1:
        nome = st.text_input("Nome Torneo")
        tipo = st.selectbox("Formato", ["Svizzero", "Girone All'Italiana"])
        data_t = st.date_input("Data", datetime.now())
        if st.button("Crea") and nome and ws_tornei is not None:
            def _create():
                id_t = f"TOR_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                ws_tornei.append_row([id_t, nome, str(data_t), tipo, "In Programmazione"])
                return id_t
            result = safe_api_call(_create)
            if result:
                st.success(f"✅ Creato! ID: {result}")
                st.rerun()
    
    with tab2:
        if not df_tornei.empty and ws_partite is not None:
            sel = st.selectbox("Torneo", df_tornei['Nome'].tolist())
            t_data = df_tornei[df_tornei['Nome']==sel].iloc[0]
            tid = t_data['ID_Torneo']
            
            if st.button("🔄 Genera Abbinamenti"):
                players = df_giocatori.to_dict('records') if not df_giocatori.empty else []
                past = df_partite[df_partite['ID_Torneo']==tid].to_dict('records') if not df_partite.empty else []
                pairings = swiss_pairing(players, past)
                st.session_state['pairings'] = pairings
                st.success(f"Generati {len(pairings)} incontri")
            
            if 'pairings' in st.session_state:
                round_n = len(df_partite[df_partite['ID_Torneo']==tid]['Round'].unique()) + 1 if not df_partite.empty else 1
                st.write(f"Round #{round_n}")
                for i, (p1, p2) in enumerate(st.session_state['pairings']):
                    c1, c2, c3 = st.columns([2,2,1])
                    with c1: st.write(f"🤍 {p1['Nome']} ({p1['Rating']})")
                    with c2: st.write(f"🖤 {p2['Nome']} ({p2['Rating']})")
                    with c3:
                        res = st.selectbox("Ris.", ["1-0","0.5-0.5","0-1"], key=f"m{i}")
                        st.session_state[f'res_{i}'] = res
                
                if st.button("💾 Salva"):
                    def _save():
                        for i, (p1, p2) in enumerate(st.session_state['pairings']):
                            res = st.session_state[f'res_{i}']
                            ws_partite.append_row([tid, round_n, p1['Nome'], p2['Nome'], res])
                            score = 1.0 if res=="1-0" else 0.5 if res=="0.5-0.5" else 0.0
                            r1, r2 = p1['Rating'], p2['Rating']
                            n1, n2 = calculate_elo(r1, r2, score)
                            if ws_giocatori is not None:
                                idx1 = df_giocatori[df_giocatori['Nome']==p1['Nome']].index[0] + 2
                                idx2 = df_giocatori[df_giocatori['Nome']==p2['Nome']].index[0] + 2
                                ws_giocatori.update_cell(idx1, 3, n1)
                                ws_giocatori.update_cell(idx2, 3, n2)
                    safe_api_call(_save)
                    st.success("✅ Salvato!")
                    st.session_state['pairings'] = None
                    st.rerun()
    
    with tab3:
        if not df_giocatori.empty:
            st.dataframe(df_giocatori, use_container_width=True)
        with st.expander("➕ Aggiungi"):
            nome = st.text_input("Nome")
            rating = st.number_input("Rating", value=RATING_INIZIALE)
            if st.button("Aggiungi") and ws_giocatori is not None:
                def _add():
                    ws_giocatori.append_row([f"PL_{datetime.now().strftime('%Y%m%d%H%M%S')}", nome, rating, ""])
                safe_api_call(_add)
                st.success("✅ Aggiunto!")
                st.rerun()

st.divider()
st.markdown("<div style='text-align:center;color:gray;font-size:12px;'>⚠️ App Amatoriale - Non Ufficiale FIDE</div>", unsafe_allow_html=True)
