import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import json

# --- CONFIGURAZIONE ---
SHEET_NAME = "Scacchi_DB"
K_FACTOR = 32
RATING_INIZIALE = 1500

st.set_page_config(page_title="Federazione Scacchistica", layout="wide", page_icon="♟️")

# --- CONNESSIONE DATABASE ---
@st.cache_resource
def get_gc():
    try:
        secrets = st.secrets["google_credentials"]
        credentials_info = json.loads(secrets["json_content"])
        
        # Scopes espliciti per Sheets e Drive
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        creds = Credentials.from_service_account_info(
            credentials_info,
            scopes=scopes
        )
        gc = gspread.authorize(creds)
        return gc
    except Exception as e:
        st.error(f"❌ Errore connessione Google: {str(e)}")
        return None

def get_sheet_data(gc, sheet_name, worksheet_name):
    try:
        spreadsheet = gc.open(sheet_name)
        worksheet = spreadsheet.worksheet(worksheet_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data), worksheet, spreadsheet
    except gspread.exceptions.WorksheetNotFound:
        st.error(f"❌ Foglio '{worksheet_name}' NON TROVATO.")
        return pd.DataFrame(), None, None
    except gspread.exceptions.SpreadsheetNotFound:
        st.error(f"❌ File '{sheet_name}' NON TROVATO.")
        return pd.DataFrame(), None, None
    except Exception as e:
        st.error(f"❌ Errore generico: {str(e)}")
        return pd.DataFrame(), None, None

# ... [Il resto del codice rimane uguale a prima] ...
# [Mantieni tutte le funzioni e l'interfaccia che ti ho dato nell'ultimo messaggio]

# --- FUNZIONI LOGICHE ---
def calculate_elo(rating_a, rating_b, score_a):
    expected_a = 1 / (1 + 10 ** ((rating_b - rating_a) / 400))
    new_a = rating_a + K_FACTOR * (score_a - expected_a)
    new_b = rating_b + K_FACTOR * ((1 - score_a) - (1 - expected_a))
    return round(new_a), round(new_b)

def swiss_pairing(players, past_matches):
    """Algoritmo Svizzero Semplificato"""
    players_sorted = sorted(players, key=lambda x: x['Rating'], reverse=True)
    pairings = []
    paired = set()
    
    for i, p1 in enumerate(players_sorted):
        if p1['Nome'] in paired:
            continue
        for j, p2 in enumerate(players_sorted[i+1:], start=i+1):
            if p2['Nome'] in paired:
                continue
            # Evita rematch
            history = [(m['Giocatore1'], m['Giocatore2']) for m in past_matches]
            if (p1['Nome'], p2['Nome']) in history or (p2['Nome'], p1['Nome']) in history:
                continue
            
            pairings.append((p1, p2))
            paired.add(p1['Nome'])
            paired.add(p2['Nome'])
            break
    return pairings

# --- GESTIONE SESSIONE E LOGIN ---
if 'admin_logged_in' not in st.session_state:
    st.session_state.admin_logged_in = False

def check_admin():
    if not st.session_state.admin_logged_in:
        st.warning("🔒 Devi effettuare il login per accedere a questa sezione.")
        return False
    return True

def logout():
    st.session_state.admin_logged_in = False
    st.rerun()

# --- INTERFACCIA PRINCIPALE ---
st.title("♟️ Federazione Scacchistica Amatoriale")

# Inizializza connessione
gc = get_gc()
if gc:
    df_giocatori, ws_giocatori, _ = get_sheet_data(gc, SHEET_NAME, "Giocatori")
    df_tornei, ws_tornei, _ = get_sheet_data(gc, SHEET_NAME, "Tornei")
    df_partite, ws_partite, _ = get_sheet_data(gc, SHEET_NAME, "Partite")
else:
    st.stop()

# Sidebar Menu
if st.session_state.admin_logged_in:
    menu = st.sidebar.selectbox("Menu", ["Home", "Classifica", "Tornei", "Iscriviti", "🛡️ Admin Panel"])
else:
    menu = st.sidebar.selectbox("Menu", ["Home", "Classifica", "Tornei", "Iscriviti", "🔐 Login Admin"])

# --- HOME ---
if menu == "Home":
    st.header("🏠 Benvenuto")
    col1, col2, col3 = st.columns(3)
    with col1: 
        st.metric("Giocatori", len(df_giocatori) if not df_giocatori.empty else 0)
    with col2: 
        st.metric("Tornei", len(df_tornei) if not df_tornei.empty else 0)
    with col3: 
        st.metric("Partite", len(df_partite) if not df_partite.empty else 0)
    
    st.markdown("### 📜 Regolamento")
    st.info(f"""
    - **Sistema di Rating:** Elo (K={K_FACTOR})
    - **Rating Iniziale:** {RATING_INIZIALE}
    - **Formati:** Svizzero o Girone all'Italiana
    - **Risultati:** Inseriti solo dall'organizzatore
    """)
    
    if not df_tornei.empty:
        st.markdown("### 🏆 Ultimi Tornei")
        st.dataframe(df_tornei.tail(5), use_container_width=True)

# --- CLASSIFICA ---
elif menu == "Classifica":
    st.header("🏆 Classifica Giocatori")
    if not df_giocatori.empty:
        search = st.text_input("🔍 Cerca giocatore per nome")
        if search:
            df_filtered = df_giocatori[df_giocatori['Nome'].str.contains(search, case=False, na=False)]
        else:
            df_filtered = df_giocatori
        
        df_sorted = df_filtered.sort_values("Rating", ascending=False)
        st.dataframe(df_sorted, use_container_width=True)
        
        st.markdown("### 🥇 Top 10")
        st.dataframe(df_giocatori.sort_values("Rating", ascending=False).head(10), use_container_width=True)
    else:
        st.warning("Nessun giocatore registrato.")

# --- TORNEI ---
elif menu == "Tornei":
    st.header("📅 Tornei Disponibili")
    if not df_tornei.empty:
        stato_filter = st.selectbox("Filtra per stato", ["Tutti", "In Programmazione", "In Corso", "Concluso"])
        
        if stato_filter != "Tutti":
            df_display = df_tornei[df_tornei['Stato'] == stato_filter]
        else:
            df_display = df_tornei
        
        st.dataframe(df_display, use_container_width=True)
        
        if not df_display.empty:
            selected = st.selectbox("Seleziona torneo per dettagli", df_display['Nome'].tolist())
            torneo = df_tornei[df_tornei['Nome'] == selected].iloc[0]
            
            st.markdown(f"#### {torneo['Nome']}")
            st.write(f"**Data:** {torneo['Data']}")
            st.write(f"**Formato:** {torneo['Tipo']}")
            st.write(f"**Stato:** {torneo['Stato']}")
            
            if not df_partite.empty:
                partite_torneo = df_partite[df_partite['ID_Torneo'] == torneo['ID_Torneo']]
                if not partite_torneo.empty:
                    st.markdown("##### Risultati")
                    st.dataframe(partite_torneo, use_container_width=True)
    else:
        st.info("Nessun torneo disponibile al momento.")

# --- ISCRIVITI ---
elif menu == "Iscriviti":
    st.header("📝 Iscriviti a un Torneo")
    
    if not df_tornei.empty:
        tornei_aperti = df_tornei[df_tornei['Stato'] == "In Programmazione"]
        
        if not tornei_aperti.empty:
            torneo_sel = st.selectbox("Seleziona Torneo", tornei_aperti['Nome'].tolist())
            
            st.markdown("#### I tuoi dati")
            nome_giocatore = st.text_input("Nome e Cognome")
            email = st.text_input("Email (opzionale)")
            rating_auto = st.checkbox("Ho già un rating nel sistema", value=False)
            
            if rating_auto:
                if not df_giocatori.empty:
                    giocatore_esistente = st.selectbox("Seleziona il tuo nome", df_giocatori['Nome'].tolist())
                    rating_display = df_giocatori[df_giocatori['Nome']==giocatore_esistente]['Rating'].values[0]
                    st.info(f"Il tuo rating attuale: **{rating_display}**")
                else:
                    st.warning("Nessun giocatore trovato nel sistema")
            else:
                rating_display = RATING_INIZIALE
                st.info(f"Rating iniziale: **{RATING_INIZIALE}**")
            
            if st.button("📤 Invia Iscrizione"):
                st.success("✅ **Iscrizione registrata!** Contatta l'admin per confermare.")
                st.info(f"Dettagli:\n- Torneo: {torneo_sel}\n- Nome: {nome_giocatore}\n- Rating: {rating_display}")
        else:
            st.info("🔔 Non ci sono tornei aperti al momento.")
    else:
        st.warning("Nessun torneo disponibile.")

# --- LOGIN ADMIN ---
elif menu == "🔐 Login Admin":
    st.header("🔐 Accesso Amministratore")
    password = st.text_input("Password", type="password")
    if st.button("Accedi"):
        try:
            if password == st.secrets["admin"]["password"]:
                st.session_state.admin_logged_in = True
                st.success("✅ Accesso effettuato!")
                st.rerun()
            else:
                st.error("❌ Password errata")
        except Exception as e:
            st.error(f"Errore configurazione Secrets: {e}")

# --- ADMIN PANEL ---
elif menu == "🛡️ Admin Panel":
    if not check_admin():
        st.stop()
    
    st.header("🛡️ Pannello Amministratore")
    
    if st.sidebar.button("🚪 Logout"):
        logout()
    
    tab1, tab2, tab3 = st.tabs(["📝 Crea Torneo", "🎮 Inserisci Risultati", "👤 Gestisci Giocatori"])
    
    with tab1:
        st.subheader("Crea Nuovo Torneo")
        nome_torneo = st.text_input("Nome Torneo")
        tipo_torneo = st.selectbox("Formato", ["Svizzero", "Girone All'Italiana"])
        data_torneo = st.date_input("Data", datetime.now())
        
        if st.button("📌 Crea Torneo"):
            if nome_torneo and ws_tornei is not None:
                id_torneo = f"TOR_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                ws_tornei.append_row([id_torneo, nome_torneo, str(data_torneo), tipo_torneo, "In Programmazione"])
                st.success(f"✅ Torneo creato! ID: {id_torneo}")
                st.rerun()
    
    with tab2:
        st.subheader("Inserisci Risultati Partite")
        if not df_tornei.empty and ws_partite is not None:
            torneo_sel = st.selectbox("Seleziona Torneo", df_tornei['Nome'].tolist())
            torneo_data = df_tornei[df_tornei['Nome'] == torneo_sel].iloc[0]
            id_torneo = torneo_data['ID_Torneo']
            
            if st.button("🔄 Genera Abbinamenti"):
                players = df_giocatori.to_dict('records') if not df_giocatori.empty else []
                past = df_partite[df_partite['ID_Torneo']==id_torneo].to_dict('records') if not df_partite.empty else []
                pairings = swiss_pairing(players, past)
                st.session_state['pairings'] = pairings
                st.success(f"Generati {len(pairings)} incontri")
            
            if 'pairings' in st.session_state:
                st.markdown("##### Risultati Round")
                round_num = len(df_partite[df_partite['ID_Torneo']==id_torneo]['Round'].unique()) + 1 if not df_partite.empty else 1
                st.write(f"Round #{round_num}")
                
                for i, (p1, p2) in enumerate(st.session_state['pairings']):
                    col1, col2, col3 = st.columns([2, 2, 1])
                    with col1: st.write(f"🤍 {p1['Nome']} ({p1['Rating']})")
                    with col2: st.write(f"🖤 {p2['Nome']} ({p2['Rating']})")
                    with col3: 
                        res = st.selectbox("Ris.", ["1-0", "0.5-0.5", "0-1"], key=f"m{i}")
                        st.session_state[f'res_{i}'] = res
                
                if st.button("💾 Salva Risultati"):
                    for i, (p1, p2) in enumerate(st.session_state['pairings']):
                        res = st.session_state[f'res_{i}']
                        ws_partite.append_row([id_torneo, round_num, p1['Nome'], p2['Nome'], res])
                        
                        score = 1.0 if res == "1-0" else 0.5 if res == "0.5-0.5" else 0.0
                        r1, r2 = p1['Rating'], p2['Rating']
                        n1, n2 = calculate_elo(r1, r2, score)
                        
                        # Aggiorna rating su Google Sheets
                        if ws_giocatori is not None:
                            idx1 = df_giocatori[df_giocatori['Nome']==p1['Nome']].index[0] + 2
                            idx2 = df_giocatori[df_giocatori['Nome']==p2['Nome']].index[0] + 2
                            ws_giocatori.update_cell(idx1, 3, n1)
                            ws_giocatori.update_cell(idx2, 3, n2)
                    
                    st.success("✅ Risultati e Rating salvati!")
                    st.session_state['pairings'] = None
                    st.rerun()
    
    with tab3:
        st.subheader("Gestisci Giocatori")
        if not df_giocatori.empty:
            st.dataframe(df_giocatori, use_container_width=True)
        
        with st.expander("➕ Aggiungi Giocatore"):
            nome = st.text_input("Nome")
            rating = st.number_input("Rating Iniziale", value=RATING_INIZIALE)
            if st.button("Aggiungi") and ws_giocatori is not None:
                ws_giocatori.append_row([f"PL_{datetime.now().strftime('%Y%m%d%H%M%S')}", nome, rating, ""])
                st.success("✅ Aggiunto!")
                st.rerun()

# --- FOOTER ---
st.divider()
st.markdown("<div style='text-align:center;color:gray;font-size:12px;'>⚠️ App Amatoriale - Non Ufficiale FIDE | Solo lettura per utenti non autorizzati</div>", unsafe_allow_html=True)
