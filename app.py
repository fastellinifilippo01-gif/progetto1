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
CACHE_TTL = 60  # Cache valida 60 secondi (limite Google)

st.set_page_config(page_title="FFchess", layout="wide", page_icon="♟️")

# --- CONNESSIONE DATABASE ---
@st.cache_resource
def get_gc():
    """Connessione persistente a Google API"""
    try:
        secrets = st.secrets["google_credentials"]
        credentials_info = json.loads(secrets["json_content"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Errore connessione: {str(e)}")
        return None

@st.cache_data(ttl=CACHE_TTL, hash_funcs={gspread.client.Client: lambda _: None})
def fetch_sheet_data(spreadsheet, worksheet_name):
    """Legge un singolo foglio - CACHED per 60 secondi"""
    try:
        worksheet = spreadsheet.worksheet(worksheet_name)
        return pd.DataFrame(worksheet.get_all_records()), worksheet
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(), None
    except Exception as e:
        return pd.DataFrame(), None

def get_all_data_cached(gc, sheet_name, cache_key):
    """Legge tutti i fogli con caching intelligente"""
    try:
        spreadsheet = gc.open(sheet_name)
        data = {}
        for ws_name in ["Giocatori", "Tornei", "Partite", "Partecipanti"]:
            df, ws = fetch_sheet_data(spreadsheet, ws_name)
            data[ws_name] = (df, ws)
        return data, spreadsheet
    except Exception as e:
        st.error(f"❌ Errore lettura: {str(e)}")
        return {}, None

def safe_api_call(func, max_retries=3):
    """Retry automatico per errori 429"""
    for attempt in range(max_retries):
        try:
            return func()
        except gspread.exceptions.APIError as e:
            if "429" in str(e):
                if attempt < max_retries - 1:
                    wait = 2 ** attempt
                    st.warning(f"⏳ Limite API: attendo {wait}s...")
                    time.sleep(wait)
                else:
                    st.error("❌ Troppe richieste. Usa il pulsante 🔄 Refresh tra 1 minuto.")
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
    pairings, paired = [], set()
    
    # Gestione bye
    bye_player = None
    if len(players_sorted) % 2 == 1:
        for p in reversed(players_sorted):
            if p['Nome'] not in paired:
                bye_player = p
                paired.add(p['Nome'])
                break
    
    for i, p1 in enumerate(players_sorted):
        if p1['Nome'] in paired:
            continue
        for p2 in players_sorted[i+1:]:
            if p2['Nome'] in paired:
                continue
            history = [(m['Giocatore1'], m['Giocatore2']) for m in past_matches if m.get('Giocatore2')]
            if (p1['Nome'], p2['Nome']) in history or (p2['Nome'], p1['Nome']) in history:
                continue
            pairings.append((p1, p2))
            paired.update([p1['Nome'], p2['Nome']])
            break
    return pairings, bye_player

# --- GESTIONE SESSIONE ---
if 'admin_logged_in' not in st.session_state:
    st.session_state.admin_logged_in = False
if 'data_cache_key' not in st.session_state:
    st.session_state.data_cache_key = 0
if 'last_data_load' not in st.session_state:
    st.session_state.last_data_load = 0

def check_admin():
    if not st.session_state.admin_logged_in:
        st.warning("🔒 Accesso admin richiesto.")
        return False
    return True

def logout():
    st.session_state.admin_logged_in = False
    st.rerun()

def refresh_data():
    """Forza refresh dei dati incrementando la cache key"""
    st.session_state.data_cache_key += 1
    st.session_state.last_data_load = time.time()
    st.rerun()

# --- INTERFACCIA ---
st.title("♟️ FFchess")

# Pulsante refresh sempre visibile per admin
if st.session_state.admin_logged_in:
    if st.sidebar.button("🔄 Refresh Dati", help="Ricarica dati da Google Sheets"):
        refresh_data()

# Carica dati (con caching)
gc = get_gc()
if not gc:
    st.stop()

data, spreadsheet = get_all_data_cached(gc, SHEET_NAME, st.session_state.data_cache_key)
df_giocatori, ws_giocatori = data.get("Giocatori", (pd.DataFrame(), None))
df_tornei, ws_tornei = data.get("Tornei", (pd.DataFrame(), None))
df_partite, ws_partite = data.get("Partite", (pd.DataFrame(), None))
df_partecipanti, ws_partecipanti = data.get("Partecipanti", (pd.DataFrame(), None))

# Sidebar Menu
menu_options = ["🏠 Home", "🏆 Classifica FIDE", "📅 Tornei"]
if st.session_state.admin_logged_in:
    menu_options += ["🛡️ Admin", "🚪 Logout"]
else:
    menu_options += ["🔐 Login Admin"]
menu = st.sidebar.selectbox("Menu", menu_options)

if menu == "🚪 Logout":
    logout()

# --- HOME ---
if menu == "🏠 Home":
    st.header("Benvenuto su FFchess")
    col1, col2, col3 = st.columns(3)
    with col1: st.metric("Giocatori", len(df_giocatori) if not df_giocatori.empty else 0)
    with col2: st.metric("Tornei", len(df_tornei) if not df_tornei.empty else 0)
    with col3: st.metric("Partite", len(df_partite) if not df_partite.empty else 0)
    
    st.divider()
    st.markdown("### 🏆 Ultimi Tornei")
    if not df_tornei.empty:
        st.dataframe(df_tornei.tail(5), use_container_width=True)

# --- CLASSIFICA FIDE ---
elif menu == "🏆 Classifica FIDE":
    st.header("🏆 Classifica Generale FIDE")
    if not df_giocatori.empty:
        search = st.text_input("🔍 Cerca")
        df_show = df_giocatori[df_giocatori['Nome'].str.contains(search, case=False, na=False)] if search else df_giocatori
        st.dataframe(df_show.sort_values("Rating", ascending=False).reset_index(drop=True), use_container_width=True)

# --- TORNEI ---
elif menu == "📅 Tornei":
    st.header("📅 Tornei")
    if not df_tornei.empty:
        sel = st.selectbox("Seleziona Torneo", df_tornei['Nome'].tolist())
        t = df_tornei[df_tornei['Nome']==sel].iloc[0]
        tid = t['ID_Torneo']
        
        col1, col2, col3 = st.columns(3)
        with col1: st.metric("Formato", t['Tipo'])
        with col2: st.metric("Stato", t['Stato'])
        with col3: st.metric("Data", t['Data'])
        
        st.divider()
        st.subheader("🏅 Classifica Torneo")
        if not df_partite.empty and not df_partecipanti.empty:
            partecipanti = df_partecipanti[df_partecipanti['ID_Torneo']==tid]['Nome'].tolist()
            punti = {}
            for nome in partecipanti:
                p = 0
                for _, row in df_partite[(df_partite['ID_Torneo']==tid) & ((df_partite['Giocatore1']==nome)|(df_partite['Giocatore2']==nome))].iterrows():
                    if pd.isna(row['Giocatore2']): p += 1.0
                    elif row['Giocatore1']==nome:
                        if row['Risultato']=="1-0": p+=1
                        elif row['Risultato']=="0.5-0.5": p+=0.5
                    else:
                        if row['Risultato']=="0-1": p+=1
                        elif row['Risultato']=="0.5-0.5": p+=0.5
                punti[nome] = p
            df_cl = pd.DataFrame([{"Nome":n,"Punti":p,"FIDE":df_giocatori[df_giocatori['Nome']==n]['Rating'].values[0] if not df_giocatori[df_giocatori['Nome']==n].empty else 0} for n,p in punti.items()]).sort_values("Punti",ascending=False)
            st.dataframe(df_cl.reset_index(drop=True), use_container_width=True)
        
        st.divider()
        st.subheader("♟️ Partite")
        if not df_partite.empty:
            st.dataframe(df_partite[df_partite['ID_Torneo']==tid], use_container_width=True)

# --- LOGIN ---
elif menu == "🔐 Login Admin":
    st.header("🔐 Accesso")
    pwd = st.text_input("Password", type="password")
    if st.button("Accedi"):
        if pwd == st.secrets["admin"]["password"]:
            st.session_state.admin_logged_in = True
            st.success("✅ Accesso!")
            st.rerun()
        else:
            st.error("❌ Password errata")

# --- ADMIN ---
elif menu == "🛡️ Admin":
    if not check_admin(): st.stop()
    
    tab1, tab2, tab3 = st.tabs(["📝 Nuovo", "🎮 Partite", "👤 Giocatori"])
    
    with tab1:
        st.subheader("📝 Crea Torneo")
        col1, col2 = st.columns(2)
        with col1:
            nome = st.text_input("Nome")
            tipo = st.selectbox("Formato", ["Svizzero", "Girone"])
        with col2:
            data = st.date_input("Data", datetime.now())
        bye_pts = st.selectbox("Punti Bye", [1.0, 0.5])
        
        partecipanti = st.multiselect("Giocatori", df_giocatori['Nome'].tolist()) if not df_giocatori.empty else []
        
        if st.button("📌 Crea", type="primary"):
            if nome and partecipanti:
                def _create():
                    tid = f"TOR_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    ws_tornei.append_row([tid, nome, str(data), tipo, "In Corso", bye_pts])
                    if ws_partecipanti:
                        for p in partecipanti: ws_partecipanti.append_row([tid, p])
                    return tid
                res = safe_api_call(_create)
                if res: st.success(f"✅ Creato! {len(partecipanti)} giocatori"); refresh_data()
    
    with tab2:
        st.subheader("🎮 Gestisci Partite")
        if not df_tornei.empty:
            sel = st.selectbox("Torneo", df_tornei['Nome'].tolist(), key="adm_t")
            t = df_tornei[df_tornei['Nome']==sel].iloc[0]
            tid, bye_val = t['ID_Torneo'], t.get('Bye', 1.0)
            
            part_names = df_partecipanti[df_partecipanti['ID_Torneo']==tid]['Nome'].tolist() if not df_partecipanti.empty else []
            players = df_giocatori[df_giocatori['Nome'].isin(part_names)].to_dict('records') if df_giocatori is not None else []
            
            if st.button("🔄 Genera Round"):
                past = df_partite[df_partite['ID_Torneo']==tid].to_dict('records') if not df_partite.empty else []
                pairings, bye = swiss_pairing(players, past)
                st.session_state.update({'pairings':pairings,'bye':bye,'round':df_partite[df_partite['ID_Torneo']==tid]['Round'].max()+1 if not df_partite.empty else 1})
                st.success(f"✅ {len(pairings)} abbinamenti" + (f" | Bye: {bye['Nome']}" if bye else ""))
            
            if 'pairings' in st.session_state:
                rn = st.session_state['round']
                for i,(p1,p2) in enumerate(st.session_state['pairings']):
                    c1,c2,c3 = st.columns([2,2,1])
                    with c1: st.write(f"🤍 {p1['Nome']}" + (f" **BYE**" if p2 is None else f" ({p1['Rating']})"))
                    with c2: st.write(f"🖤 {p2['Nome']} ({p2['Rating']})" if p2 else f"⚪ +{bye_val} pt")
                    with c3:
                        if p2 is None: st.selectbox("Ris.",["Bye"],key=f"r{i}",disabled=True); st.session_state[f"res{i}"]="Bye"
                        else: st.session_state[f"res{i}"] = st.selectbox("Ris.",["1-0","0.5-0.5","0-1"],key=f"r{i}")
                
                if st.button("💾 Salva", type="primary"):
                    def _save():
                        for i,(p1,p2) in enumerate(st.session_state['pairings']):
                            res = st.session_state[f"res{i}"]
                            if p2 is None:
                                ws_partite.append_row([tid, rn, p1['Nome'], None, "Bye"])
                            else:
                                ws_partite.append_row([tid, rn, p1['Nome'], p2['Nome'], res])
                                score = 1.0 if res=="1-0" else 0.5 if res=="0.5-0.5" else 0.0
                                n1,n2 = calculate_elo(p1['Rating'], p2['Rating'], score)
                                if ws_giocatori is not None:
                                    for nome,n in [(p1['Nome'],n1),(p2['Nome'],n2)]:
                                        idx = df_giocatori[df_giocatori['Nome']==nome].index[0]+2
                                        ws_giocatori.update_cell(idx, 3, n)
                    safe_api_call(_save)
                    st.success("✅ Salvato!"); st.session_state.pop('pairings',None); refresh_data()
    
    with tab3:
        st.subheader("👤 Giocatori")
        if not df_giocatori.empty: st.dataframe(df_giocatori.sort_values("Rating",ascending=False), use_container_width=True)
        with st.expander("➕ Aggiungi"):
            nome, rating = st.text_input("Nome"), st.number_input("Rating", value=RATING_INIZIALE)
            if st.button("Aggiungi") and ws_giocatori:
                safe_api_call(lambda: ws_giocatori.append_row([f"PL_{datetime.now().strftime('%Y%m%d')}", nome, rating, ""]))
                st.success("✅ Aggiunto!"); refresh_data()

st.divider()
st.markdown("<div style='text-align:center;color:gray;font-size:12px;'>⚠️ FFchess - App Amatoriale Non Ufficiale FIDE</div>", unsafe_allow_html=True)
