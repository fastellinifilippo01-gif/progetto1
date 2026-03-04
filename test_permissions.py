import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json

st.title("🔍 Test Permessi Google Sheets")

# Carica secrets
try:
    secrets = st.secrets["google_credentials"]
    credentials_info = json.loads(secrets["json_content"])
    st.success("✅ Secrets caricati correttamente")
except Exception as e:
    st.error(f"❌ Errore Secrets: {e}")
    st.stop()

# Autorizza
try:
    creds = Credentials.from_service_account_info(
        credentials_info,
        scopes=["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    )
    gc = gspread.authorize(creds)
    st.success("✅ Service Account autorizzata")
    st.write(f"**Email Service Account:** `{credentials_info.get('client_email', 'N/A')}`")
except Exception as e:
    st.error(f"❌ Errore autorizzazione: {e}")
    st.stop()

# Prova ad aprire il foglio
SHEET_NAME = "Scacchi_DB"
try:
    spreadsheet = gc.open(SHEET_NAME)
    st.success(f"✅ File '{SHEET_NAME}' trovato!")
    st.write(f"**ID Foglio:** `{spreadsheet.id}`")
    st.write(f"**URL:** {spreadsheet.url}")
except Exception as e:
    st.error(f"❌ File '{SHEET_NAME}' NON trovato: {e}")
    st.info("1) Controlla il nome esatto del file\n2) Condividi il foglio con l'email della Service Account")
    st.stop()

# Prova a scrivere
try:
    worksheet = spreadsheet.worksheet("Giocatori")
    st.success("✅ Foglio 'Giocatori' trovato!")
    
    # Test scrittura
    if st.button("🧪 Test Scrittura"):
        worksheet.append_row([f"TEST_{int(__import__('time').time())}", "Test User", "1500", ""])
        st.success("✅ Scrittura riuscita! Controlla il foglio Google.")
except Exception as e:
    st.error(f"❌ Errore scrittura: {e}")
    st.info("Condividi il foglio con l'email della Service Account come EDITOR")
