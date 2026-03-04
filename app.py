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
CACHE_TTL = 60

st.set_page_config(page_title="FFchess", layout="wide", page_icon="♟️")

# --- CONNESSIONE DATABASE ---
@st.cache_resource
def get_gc():
    try:
        secrets = st.secrets["google_credentials"]
        credentials_info = json.loads(secrets["json_content"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(credentials_info, scopes=scopes)
        gc = gspread.authorize(creds)
        # Test connessione
        gc.open(SHEET_NAME)
        return gc
    except Exception as e:
        st.error(f"❌ Errore connessione: {str(e)}")
        return None

@st.cache_data(ttl=CACHE_TTL)
def fetch_sheet_data(_spreadsheet, worksheet_name):
    try:
        worksheet = _spreadsheet.worksheet(worksheet_name)
        return pd.DataFrame(worksheet.get_all_records()), worksheet
    except:
        return pd.DataFrame(), None

def get_all_data_cached(gc, sheet_name, cache_key):
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
    for attempt in range(max_retries):
        try:
            return func()
        except gspread.exceptions.APIError as e:
            if "429" in str(e):
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    st.error("❌ Troppe richieste. Usa 🔄 Refresh tra 1 minuto.")
                    return None
            raise
        except Exception as e:
            st.error(f"❌ Errore API: {str(e)}")
            return None
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

# --- SESSIONE ---
if 'admin_logged_in' not in st.session_state:
    st.session_state.admin_logged_in = False
if 'data_cache_key' not in st.session_state:
    st.session_state.data_cache_key = 0

def check_admin():
    if not st.session_state.admin_logged_in:
        st.warning("🔒 Accesso admin richiesto.")
        return False
    return True

def logout():
    st.session_state.admin_logged_in = False
    st.rerun()

def refresh_data():
    st.session_state.data_cache_key += 1
    st.rerun()

# --- INTERFACCIA ---
st.title("♟️ FFchess")

if st.session_state.admin_logged_in:
    if st.sidebar.button("🔄 Refresh Dati", key="btn_refresh"):
        refresh_data()

gc = get_gc()
if not gc:
    st.stop()

data, spreadsheet = get_all_data_cached(gc, SHEET_NAME, st.session_state.data_cache_key)
df_giocatori, ws_giocatori = data.get("Giocatori", (pd.DataFrame(), None))
df_tornei, ws_tornei = data.get("Tornei", (pd.DataFrame(), None))
df_partite, ws_partite = data.get("Partite", (pd.DataFrame(), None))
df_partecipanti, ws_partecipanti = data.get("Partecipanti", (pd.DataFrame(), None))

# Verifica permessi scrittura
if ws_giocatori is None:
    st.error("❌ Nessun accesso in scrittura al foglio 'Giocatori'. Controlla i permessi della Service Account.")

menu_opts = ["🏠 Home", "🏆 Classifica FIDE", "📅 Tornei"]
if st.session_state.admin_logged_in:
    menu_opts += ["🛡️ Admin", "🚪 Logout"]
else:
    menu_opts += ["🔐 Login Admin"]
menu = st.sidebar.selectbox("Menu", menu_opts, key="sel_menu")

if menu == "🚪 Logout":
    logout()

# --- HOME ---
if menu == "🏠 Home":
    st.header("Benvenuto su FFchess")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("Giocatori", len(df_giocatori) if not df_giocatori.empty else 0)
    with c2:
        st.metric("Tornei", len(df_tornei) if not df_tornei.empty else 0)
    with c3:
        st.metric("Partite", len(df_partite) if not df_partite.empty else 0)
    st.divider()
    if not df_tornei.empty:
        st.dataframe(df_tornei.tail(5), use_container_width=True)

# --- CLASSIFICA FIDE ---
elif menu == "🏆 Classifica FIDE":
    st.header("🏆 Classifica Generale FIDE")
    if not df_giocatori.empty:
        search = st.text_input("🔍 Cerca", key="txt_search_fide")
        df_s = df_giocatori[df_giocatori['Nome'].str.contains(search, case=False, na=False)] if search else df_giocatori
        st.dataframe(df_s.sort_values("Rating", ascending=False).reset_index(drop=True), use_container_width=True)

# --- TORNEI ---
elif menu == "📅 Tornei":
    st.header("📅 Tornei")
    if not df_tornei.empty:
        sel = st.selectbox("Seleziona", df_tornei['Nome'].tolist(), key="sel_torneo")
        t = df_tornei[df_tornei['Nome'] == sel].iloc[0]
        tid = t['ID_Torneo']
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Formato", t['Tipo'])
        with c2:
            st.metric("Stato", t['Stato'])
        with c3:
            st.metric("Data", t['Data'])
        st.divider()
        st.subheader("🏅 Classifica Torneo")
        if not df_partite.empty and not df_partecipanti.empty:
            part = df_partecipanti[df_partecipanti['ID_Torneo'] == tid]['Nome'].tolist()
            pts = {}
            for n in part:
                p = 0
                for _, r in df_partite[(df_partite['ID_Torneo'] == tid) & ((df_partite['Giocatore1'] == n) | (df_partite['Giocatore2'] == n))].iterrows():
                    if pd.isna(r['Giocatore2']):
                        p += 1.0
                    elif r['Giocatore1'] == n:
                        if r['Risultato'] == "1-0":
                            p += 1
                        elif r['Risultato'] == "0.5-0.5":
                            p += 0.5
                    else:
                        if r['Risultato'] == "0-1":
                            p += 1
                        elif r['Risultato'] == "0.5-0.5":
                            p += 0.5
                pts[n] = p
            df_cl = pd.DataFrame([{"Nome": n, "Punti": pts[n], "FIDE": df_giocatori[df_giocatori['Nome'] == n]['Rating'].values[0] if not df_giocatori[df_giocatori['Nome'] == n].empty else 0} for n in pts]).sort_values("Punti", ascending=False)
            st.dataframe(df_cl.reset_index(drop=True), use_container_width=True)
        st.divider()
        if not df_partite.empty:
            st.dataframe(df_partite[df_partite['ID_Torneo'] == tid], use_container_width=True)

# --- LOGIN ---
elif menu == "🔐 Login Admin":
    st.header("🔐 Accesso")
    pwd = st.text_input("Password", type="password", key="txt_pwd")
    if st.button("Accedi", key="btn_login"):
        if pwd == st.secrets["admin"]["password"]:
            st.session_state.admin_logged_in = True
            st.success("✅ Accesso effettuato!")
            st.rerun()
        else:
            st.error("❌ Password errata")

# --- ADMIN ---
elif menu == "🛡️ Admin":
    if not check_admin():
        st.stop()
    
    tab1, tab2, tab3 = st.tabs(["📝 Nuovo Torneo", "🎮 Gestisci Partite", "👤 Giocatori"])
    
    # TAB 1: CREA TORNEO
    with tab1:
        st.subheader("📝 Crea Nuovo Torneo")
        c1, c2 = st.columns(2)
        with c1:
            nome_torneo = st.text_input("Nome Torneo", key="txt_nome_torneo")
            tipo_torneo = st.selectbox("Formato", ["Svizzero", "Girone"], key="sel_tipo_torneo")
        with c2:
            data_torneo = st.date_input("Data", datetime.now(), key="dt_data_torneo")
        bye_pts = st.selectbox("Punti Bye", [1.0, 0.5], key="sel_bye")
        
        partecipanti = []
        if not df_giocatori.empty:
            partecipanti = st.multiselect("Giocatori", df_giocatori['Nome'].tolist(), key="ms_partecipanti")
        
        if st.button("📌 Crea Torneo", type="primary", key="btn_crea_torneo"):
            if nome_torneo and partecipanti and ws_tornei is not None:
                def _create():
                    tid = f"TOR_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    ws_tornei.append_row([tid, nome_torneo, str(data_torneo), tipo_torneo, "In Corso", bye_pts])
                    if ws_partecipanti:
                        for p in partecipanti:
                            ws_partecipanti.append_row([tid, p])
                    return tid
                res = safe_api_call(_create)
                if res:
                    st.success(f"✅ Torneo creato! {len(partecipanti)} giocatori")
                    refresh_data()
    
    # TAB 2: GESTISCI PARTITE
    with tab2:
        st.subheader("🎮 Gestisci Partite")
        if not df_tornei.empty:
            sel_torneo = st.selectbox("Torneo", df_tornei['Nome'].tolist(), key="sel_admin_torneo")
            t = df_tornei[df_tornei['Nome'] == sel_torneo].iloc[0]
            tid = t['ID_Torneo']
            bye_val = t.get('Bye', 1.0)
            
            pn = df_partecipanti[df_partecipanti['ID_Torneo'] == tid]['Nome'].tolist() if not df_partecipanti.empty else []
            pl = df_giocatori[df_giocatori['Nome'].isin(pn)].to_dict('records') if df_giocatori is not None and not df_giocatori.empty else []
            
            if not pl:
                st.warning("Nessun partecipante per questo torneo.")
            else:
                if st.button("🔄 Genera Round", key="btn_genera_round"):
                    past = df_partite[df_partite['ID_Torneo'] == tid].to_dict('records') if not df_partite.empty else []
                    pr, bye = swiss_pairing(pl, past)
                    st.session_state['pairings'] = pr
                    st.session_state['bye'] = bye
                    st.session_state['current_round'] = df_partite[df_partite['ID_Torneo'] == tid]['Round'].max() + 1 if not df_partite.empty and 'Round' in df_partite.columns else 1
                    st.success(f"✅ {len(pr)} abbinamenti" + (f" | Bye: {bye['Nome']}" if bye else ""))
                
                if 'pairings' in st.session_state:
                    rn = st.session_state['current_round']
                    st.write(f"**Round #{rn}**")
                    for i, (p1, p2) in enumerate(st.session_state['pairings']):
                        c1, c2, c3 = st.columns([2, 2, 1])
                        with c1:
                            if p2 is None:
                                st.write(f"🤍 {p1['Nome']} ({p1['Rating']}) - **BYE**")
                            else:
                                st.write(f"🤍 {p1['Nome']} ({p1['Rating']})")
                        with c2:
                            if p2 is None:
                                st.write(f"⚪ +{bye_val} punti torneo")
                            else:
                                st.write(f"🖤 {p2['Nome']} ({p2['Rating']})")
                        with c3:
                            if p2 is None:
                                st.selectbox("Ris.", ["Bye"], key=f"res_bye_{i}", disabled=True)
                                st.session_state[f"res_{i}"] = "Bye"
                            else:
                                st.session_state[f"res_{i}"] = st.selectbox("Ris.", ["1-0", "0.5-0.5", "0-1"], key=f"res_{i}")
                    
                    if st.button("💾 Salva Risultati", type="primary", key="btn_salva_risultati"):
                        def _save():
                            for i, (p1, p2) in enumerate(st.session_state['pairings']):
                                res = st.session_state[f"res_{i}"]
                                if p2 is None:
                                    ws_partite.append_row([tid, rn, p1['Nome'], None, "Bye"])
                                else:
                                    ws_partite.append_row([tid, rn, p1['Nome'], p2['Nome'], res])
                                    sc = 1.0 if res == "1-0" else 0.5 if res == "0.5-0.5" else 0.0
                                    n1, n2 = calculate_elo(p1['Rating'], p2['Rating'], sc)
                                    if ws_giocatori is not None:
                                        for nm, v in [(p1['Nome'], n1), (p2['Nome'], n2)]:
                                            idx = df_giocatori[df_giocatori['Nome'] == nm].index[0] + 2
                                            ws_giocatori.update_cell(idx, 3, v)
                        safe_api_call(_save)
                        st.success("✅ Risultati salvati!")
                        st.session_state.pop('pairings', None)
                        st.session_state.pop('current_round', None)
                        refresh_data()
    
    # TAB 3: GIOCATORI
    with tab3:
        st.subheader("👤 Gestione Giocatori")
        if not df_giocatori.empty:
            st.dataframe(df_giocatori.sort_values("Rating", ascending=False).reset_index(drop=True), use_container_width=True)
        
        st.divider()
        st.subheader("➕ Aggiungi Giocatore")
        
        if ws_giocatori is None:
            st.error("❌ Nessun accesso in scrittura. Controlla i permessi.")
        else:
            c1, c2 = st.columns(2)
            with c1:
                nome_giocatore = st.text_input("Nome", key="txt_nome_giocatore")
            with c2:
                rating_giocatore = st.number_input("Rating", value=RATING_INIZIALE, key="num_rating_giocatore")
            
            if st.button("Aggiungi", key="btn_aggiungi_giocatore"):
                if nome_giocatore:
                    def _add():
                        ws_giocatori.append_row([f"PL_{datetime.now().strftime('%Y%m%d%H%M%S')}", nome_giocatore, rating_giocatore, ""])
                    safe_api_call(_add)
                    st.success("✅ Giocatore aggiunto!")
                    refresh_data()

st.divider()
st.markdown("<div style='text-align:center;color:gray;font-size:12px;'>⚠️ FFchess - App Amatoriale Non Ufficiale FIDE</div>", unsafe_allow_html=True)
