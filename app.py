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

st.set_page_config(page_title="FFchess", layout="wide", page_icon="♟️")

# --- CONNESSIONE DATABASE ---
@st.cache_resource
def get_gc():
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
    try:
        spreadsheet = gc.open(sheet_name)
        data = {}
        for ws_name in ["Giocatori", "Tornei", "Partite", "Round"]:
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

def swiss_pairing(players, past_matches, paired_bye=None):
    players_sorted = sorted(players, key=lambda x: x['Rating'], reverse=True)
    pairings = []
    paired = set()
    
    # Gestisci bye se numero dispari
    if len(players_sorted) % 2 == 1:
        for i, p in enumerate(players_sorted):
            if p['Nome'] not in paired and p['Nome'] != paired_bye:
                # Trova il giocatore con rating più basso disponibile per il bye
                bye_player = p
                break
        pairings.append((bye_player, None))  # None indica bye
        paired.add(bye_player['Nome'])
    
    for i, p1 in enumerate(players_sorted):
        if p1['Nome'] in paired:
            continue
        for j, p2 in enumerate(players_sorted[i+1:], start=i+1):
            if p2['Nome'] in paired:
                continue
            history = [(m['Giocatore1'], m['Giocatore2']) for m in past_matches if m['Giocatore2'] is not None]
            if (p1['Nome'], p2['Nome']) in history or (p2['Nome'], p1['Nome']) in history:
                continue
            pairings.append((p1, p2))
            paired.add(p1['Nome'])
            paired.add(p2['Nome'])
            break
    return pairings

def recalculate_ratings(df_giocatori, df_partite, df_round, torneo_id, ws_giocatori):
    """Ricalcola tutti i rating da zero per un torneo"""
    # Resetta i rating ai valori iniziali (prima del torneo)
    # Per semplicità, usiamo i rating attuali come base e ricalcoliamo solo le variazioni
    
    # Ottieni tutti i round ordinati
    rounds = df_round[df_round['ID_Torneo'] == torneo_id].sort_values('Round')
    
    # Crea copia dei rating correnti
    ratings = {}
    for _, row in df_giocatori.iterrows():
        ratings[row['Nome']] = row['Rating']
    
    # Ricalcola round per round
    for _, round_row in rounds.iterrows():
        round_num = round_row['Round']
        round_partite = df_partite[(df_partite['ID_Torneo'] == torneo_id) & (df_partite['Round'] == round_num)]
        
        for _, partita in round_partite.iterrows():
            if partita['Giocatore2'] is None or pd.isna(partita['Giocatore2']):
                # Bye - nessun cambio rating
                continue
            
            p1, p2 = partita['Giocatore1'], partita['Giocatore2']
            res = partita['Risultato']
            score = 1.0 if res == "1-0" else 0.5 if res == "0.5-0.5" else 0.0
            
            # Usa i rating "prima del round" per il calcolo
            r1 = ratings.get(p1, RATING_INIZIALE)
            r2 = ratings.get(p2, RATING_INIZIALE)
            
            n1, n2 = calculate_elo(r1, r2, score)
            
            ratings[p1] = n1
            ratings[p2] = n2
    
    # Aggiorna Google Sheets
    if ws_giocatori is not None:
        for nome, rating in ratings.items():
            try:
                idx = df_giocatori[df_giocatori['Nome'] == nome].index[0] + 2
                ws_giocatori.update_cell(idx, 3, rating)
            except:
                pass
    
    return ratings

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
st.title("♟️ FFchess")

gc = get_gc()
if not gc:
    st.stop()

data = get_all_data(gc, SHEET_NAME)
df_giocatori, ws_giocatori = data.get("Giocatori", (pd.DataFrame(), None))
df_tornei, ws_tornei = data.get("Tornei", (pd.DataFrame(), None))
df_partite, ws_partite = data.get("Partite", (pd.DataFrame(), None))
df_round, ws_round = data.get("Round", (pd.DataFrame(), None))

# Sidebar Menu
menu_options = ["Home", "Classifica", "Tornei", "Iscriviti"]
if st.session_state.admin_logged_in:
    menu_options.append("🛡️ Admin Panel")
else:
    menu_options.append("🔐 Login Admin")
menu = st.sidebar.selectbox("Menu", menu_options)

# --- HOME ---
if menu == "Home":
    st.header("🏠 Benvenuto su FFchess")
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
    st.header("🏆 Classifica Giocatori")
    if not df_giocatori.empty:
        search = st.text_input("🔍 Cerca giocatore")
        df_show = df_giocatori[df_giocatori['Nome'].str.contains(search, case=False, na=False)] if search else df_giocatori
        st.dataframe(df_show.sort_values("Rating", ascending=False), use_container_width=True)
        st.markdown("### 🥇 Top 10")
        st.dataframe(df_giocatori.sort_values("Rating", ascending=False).head(10), use_container_width=True)
    else:
        st.warning("Nessun giocatore registrato.")

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
        st.info("Nessun torneo disponibile.")

# --- ISCRIVITI ---
elif menu == "Iscriviti":
    st.header("📝 Iscrizione")
    if not df_tornei.empty:
        aperti = df_tornei[df_tornei['Stato']=="In Programmazione"]
        if not aperti.empty:
            sel = st.selectbox("Torneo", aperti['Nome'].tolist())
            nome = st.text_input("Nome")
            email = st.text_input("Email (opz.)")
            if st.button("Invia Iscrizione"):
                st.success("✅ Iscrizione inviata! Contatta l'admin per confermare.")
        else:
            st.info("Nessun torneo aperto.")
    else:
        st.warning("Nessun torneo disponibile.")

# --- LOGIN ADMIN ---
elif menu == "🔐 Login Admin":
    st.header("🔐 Accesso Amministratore")
    pwd = st.text_input("Password", type="password")
    if st.button("Accedi"):
        try:
            if pwd == st.secrets["admin"]["password"]:
                st.session_state.admin_logged_in = True
                st.success("✅ Accesso effettuato!")
                st.rerun()
            else:
                st.error("❌ Password errata")
        except:
            st.error("Errore configurazione Secrets")

# --- ADMIN PANEL ---
elif menu == "🛡️ Admin Panel":
    if not check_admin():
        st.stop()
    st.header("🛡️ Pannello Amministratore FFchess")
    if st.sidebar.button("🚪 Logout"):
        logout()
    
    tab1, tab2, tab3, tab4 = st.tabs(["📝 Crea Torneo", "🎮 Gestisci Round", "👤 Giocatori", "📜 Storico"])
    
    # --- TAB 1: CREA TORNEO ---
    with tab1:
        st.subheader("📝 Crea Nuovo Torneo")
        
        col1, col2 = st.columns(2)
        with col1:
            nome_torneo = st.text_input("Nome Torneo")
            tipo_torneo = st.selectbox("Formato", ["Svizzero", "Girone All'Italiana"])
        with col2:
            data_torneo = st.date_input("Data", datetime.now())
            stato_torneo = st.selectbox("Stato Iniziale", ["In Programmazione", "In Corso"])
        
        st.divider()
        st.subheader("⚖️ Configurazione Bye")
        st.info("Se il numero di giocatori è dispari, uno riceve il bye (riposo).")
        bye_points = st.selectbox("Punteggio per Bye", [1.0, 0.5], format_func=lambda x: f"{x} punto/i")
        st.write(f"Valore selezionato: **{bye_points}**")
        
        if st.button("📌 Crea Torneo", type="primary"):
            if nome_torneo and ws_tornei is not None:
                def _create():
                    id_t = f"TOR_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                    ws_tornei.append_row([id_t, nome_torneo, str(data_torneo), tipo_torneo, stato_torneo, bye_points])
                    # Crea entry nel foglio Round
                    if ws_round is not None:
                        ws_round.append_row([id_t, 0, "Creato", str(datetime.now())])
                    return id_t
                result = safe_api_call(_create)
                if result:
                    st.success(f"✅ Torneo creato! ID: {result}")
                    st.rerun()
    
    # --- TAB 2: GESTISCI ROUND ---
    with tab2:
        st.subheader("🎮 Gestione Round e Risultati")
        
        if not df_tornei.empty and ws_partite is not None:
            sel = st.selectbox("Seleziona Torneo", df_tornei['Nome'].tolist(), key="admin_torneo")
            t_data = df_tornei[df_tornei['Nome']==sel].iloc[0]
            tid = t_data['ID_Torneo']
            bye_val = t_data.get('Bye', 1.0)  # Valore bye dal torneo
            
            # Mostra round esistenti
            if not df_round.empty:
                round_esistenti = df_round[df_round['ID_Torneo']==tid].sort_values('Round')
                if not round_esistenti.empty:
                    st.markdown("##### 📋 Round Esistenti")
                    for _, r in round_esistenti.iterrows():
                        if r['Round'] > 0:
                            col_a, col_b, col_c = st.columns([4, 2, 1])
                            with col_a:
                                st.write(f"**Round {r['Round']}** - {r['Stato']}")
                            with col_b:
                                st.write(f"Data: {r['Data']}")
                            with col_c:
                                if st.button("🗑️ Elimina", key=f"del_round_{r['Round']}"):
                                    def _delete_round():
                                        # 1. Elimina le partite di questo round
                                        partite_round = df_partite[(df_partite['ID_Torneo']==tid) & (df_partite['Round']==r['Round'])]
                                        for idx in partite_round.index:
                                            sheet_idx = idx + 2
                                            ws_partite.delete_rows(sheet_idx)
                                        
                                        # 2. Elimina il round dal foglio Round
                                        round_row = df_round[(df_round['ID_Torneo']==tid) & (df_round['Round']==r['Round'])]
                                        for idx in round_row.index:
                                            sheet_idx = idx + 2
                                            ws_round.delete_rows(sheet_idx)
                                        
                                        # 3. Ricalcola i rating
                                        recalculate_ratings(df_giocatori, df_partite, df_round, tid, ws_giocatori)
                                    
                                    safe_api_call(_delete_round)
                                    st.success(f"✅ Round {r['Round']} eliminato! Rating ricalcolati.")
                                    st.rerun()
                    st.divider()
            
            # Genera nuovo round
            max_round = df_round[df_round['ID_Torneo']==tid]['Round'].max() if not df_round.empty else 0
            next_round = int(max_round) + 1 if max_round else 1
            
            st.markdown(f"##### 🔄 Genera Round #{next_round}")
            
            if st.button("Genera Abbinamenti", type="primary"):
                players = df_giocatori.to_dict('records') if not df_giocatori.empty else []
                past = df_partite[df_partite['ID_Torneo']==tid].to_dict('records') if not df_partite.empty else []
                pairings = swiss_pairing(players, past)
                st.session_state['pairings'] = pairings
                st.session_state['current_round'] = next_round
                st.success(f"✅ Generati {len(pairings)} incontri")
            
            if 'pairings' in st.session_state and st.session_state.get('current_round') == next_round:
                st.write(f"**Round #{next_round}**")
                
                for i, (p1, p2) in enumerate(st.session_state['pairings']):
                    col1, col2, col3 = st.columns([2, 2, 1])
                    with col1:
                        if p2 is None:
                            st.write(f"🤍 {p1['Nome']} ({p1['Rating']}) - **BYE**")
                        else:
                            st.write(f"🤍 {p1['Nome']} ({p1['Rating']})")
                    with col2:
                        if p2 is None:
                            st.write(f"⚪ Bye: {bye_val} punti")
                        else:
                            st.write(f"🖤 {p2['Nome']} ({p2['Rating']})")
                    with col3:
                        if p2 is None:
                            st.selectbox("Ris.", ["1-0 (Bye)"], key=f"m{i}", disabled=True)
                            st.session_state[f'res_{i}'] = "1-0 (Bye)"
                        else:
                            res = st.selectbox("Ris.", ["1-0", "0.5-0.5", "0-1"], key=f"m{i}")
                            st.session_state[f'res_{i}'] = res
                
                if st.button("💾 Salva Risultati", type="primary"):
                    def _save():
                        # Salva round
                        ws_round.append_row([tid, next_round, "Completato", str(datetime.now())])
                        
                        # Salva partite e aggiorna rating
                        for i, (p1, p2) in enumerate(st.session_state['pairings']):
                            res = st.session_state[f'res_{i}']
                            
                            if p2 is None:
                                # Bye - nessun cambio rating, solo registrazione
                                ws_partite.append_row([tid, next_round, p1['Nome'], None, f"Bye ({bye_val})"])
                            else:
                                # Partita normale
                                ws_partite.append_row([tid, next_round, p1['Nome'], p2['Nome'], res])
                                score = 1.0 if res=="1-0" else 0.5 if res=="0.5-0.5" else 0.0
                                r1, r2 = p1['Rating'], p2['Rating']
                                n1, n2 = calculate_elo(r1, r2, score)
                                if ws_giocatori is not None:
                                    idx1 = df_giocatori[df_giocatori['Nome']==p1['Nome']].index[0] + 2
                                    idx2 = df_giocatori[df_giocatori['Nome']==p2['Nome']].index[0] + 2
                                    ws_giocatori.update_cell(idx1, 3, n1)
                                    ws_giocatori.update_cell(idx2, 3, n2)
                    
                    safe_api_call(_save)
                    st.success("✅ Risultati salvati!")
                    st.session_state['pairings'] = None
                    st.session_state['current_round'] = None
                    st.rerun()
        else:
            st.warning("Nessun torneo disponibile.")
    
    # --- TAB 3: GIOCATORI ---
    with tab3:
        st.subheader("👤 Gestione Giocatori")
        if not df_giocatori.empty:
            st.dataframe(df_giocatori, use_container_width=True)
        with st.expander("➕ Aggiungi Giocatore"):
            nome = st.text_input("Nome")
            rating = st.number_input("Rating Iniziale", value=RATING_INIZIALE)
            if st.button("Aggiungi") and ws_giocatori is not None:
                def _add():
                    ws_giocatori.append_row([f"PL_{datetime.now().strftime('%Y%m%d%H%M%S')}", nome, rating, ""])
                safe_api_call(_add)
                st.success("✅ Aggiunto!")
                st.rerun()
    
    # --- TAB 4: STORICO ---
    with tab4:
        st.subheader("📜 Storico Partite")
        if not df_partite.empty:
            st.dataframe(df_partite, use_container_width=True)
        else:
            st.info("Nessuna partita registrata.")

st.divider()
st.markdown("<div style='text-align:center;color:gray;font-size:12px;'>⚠️ FFchess - App Amatoriale Non Ufficiale FIDE</div>", unsafe_allow_html=True)
