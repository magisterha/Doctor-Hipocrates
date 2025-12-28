import streamlit as st
import google.generativeai as genai
import json
import urllib.parse
from datetime import datetime
from fpdf import FPDF

# --- 1. CONFIGURACIÓN ---
try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except KeyError:
    st.error("⚠️ Error: Falta API Key en secrets.toml")
    st.stop()

# Usamos Flash Lite por su velocidad y ventana de contexto
generation_config = {
    "temperature": 0.2, # Muy baja para el informe (seriedad)
    "top_p": 0.95,
    "response_mime_type": "text/plain", # El informe será TEXTO, no JSON
}

model_chat = genai.GenerativeModel("gemini-2.5-flash-lite")
model_report = genai.GenerativeModel("gemini-2.5-flash-lite") # Instancia separada para el informe

# --- 2. PROMPTS ---

# Prompt 1: El Chat (Dr. Hipócrates) - Output JSON
PROMPT_TRIAJE = """
Actúa como Dr. Hipócrates. Tu objetivo es calmar y extraer síntomas.
Responde SIEMPRE en JSON.
{
  "traduccion_medica": { "motivo": "...", "sintomas": ["..."], "gravedad": "..." },
  "derivacion": { "necesaria": bool, "query_maps": "..." },
  "respuesta_paciente": "..."
}
"""

# Prompt 2: El Redactor de Informes - Output TEXTO FORMAL
PROMPT_INFORME_FINAL = """
Actúa como un Consultor Médico Senior. Tu tarea es recibir un log de datos JSON de un paciente y redactar una "CARTA DE DERIVACIÓN CLÍNICA" (Referral Letter) profesional.

OBJETIVO: Que el médico de urgencias o familia lea esto y entienda el caso en 30 segundos.

FORMATO DEL INFORME:
1.  **Cabecera:** Fecha, Hora y ID Anónimo.
2.  **Chief Complaint (Motivo de Consulta):** El síntoma principal técnico.
3.  **History of Present Illness (Anamnesis):** Narrativa cronológica basada en los datos recolectados.
4.  **Symptoms List:** Lista de síntomas detectados (usando terminología médica).
5.  **Assessment (Valoración):** Gravedad estimada y sugerencia de especialidad.
6.  **Nota:** Añade una nota indicando que este informe ha sido generado por IA (Dr. Hipócrates) y requiere validación humana.

IDIOMA:
Escribe el informe en INGLÉS MÉDICO INTERNACIONAL (Standard Medical English) para garantizar que sea legible en cualquier país, salvo que los datos indiquen claramente un país de habla hispana, en cuyo caso hazlo en Español.
"""

# --- 3. FUNCIONES PDF ---

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 15)
        self.cell(0, 10, 'Dr. Hipocrates AI - Informe de Derivacion', 0, 1, 'C')
        self.ln(10)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

def generar_pdf_desde_texto(texto_informe):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)
    
    # FPDF básico no soporta emojis ni caracteres chinos/japoneses por defecto.
    # Usamos encode/decode para limpiar caracteres no compatibles con Latin-1
    texto_limpio = texto_informe.encode('latin-1', 'replace').decode('latin-1')
    
    pdf.multi_cell(0, 7, texto_limpio)
    return pdf.output(dest='S').encode('latin-1')

def generar_link_maps(query):
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)

# --- 4. UI SETUP ---
st.set_page_config(page_title="Dr. Hipócrates", page_icon="⚕️")
st.title("⚕️ Dr. Hipócrates")
st.warning("⚠️ AVISO: Herramienta de asistencia. NO sustituye el diagnóstico médico profesional.")

# --- 5. ESTADO ---
if "chat" not in st.session_state:
    st.session_state.chat = model_chat.start_chat(history=[
        {"role": "user", "parts": "Configura tu rol con este prompt: " + PROMPT_TRIAJE},
        {"role": "model", "parts": json.dumps({"respuesta_paciente": "Entendido. Soy el Dr. Hipócrates."})}
    ])
if "historial_visual" not in st.session_state:
    st.session_state.historial_visual = [{"role": "assistant", "content": "Buenos días. Soy el Dr. Hipócrates. Describa sus síntomas."}]
if "datos_tecnicos" not in st.session_state:
    st.session_state.datos_tecnicos = []

# --- 6. CHAT LOOP ---
chat_container = st.container()

with chat_container:
    for msg in st.session_state.historial_visual:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            if "map_url" in msg:
                st.link_button(f"📍 {msg['map_label']}", msg["map_url"])
                if msg.get("is_emerg"): st.error("🚨 POSIBLE EMERGENCIA")

user_input = st.chat_input("Escriba aquí...")

if user_input:
    st.session_state.historial_visual.append({"role": "user", "content": user_input})
    with chat_container:
        st.chat_message("user").write(user_input)
    
    with chat_container:
        with st.chat_message("assistant"):
            with st.spinner("Analizando..."):
                try:
                    # 1. Llamada al Chat (Flash Lite)
                    response = st.session_state.chat.send_message(user_input)
                    # Forzamos limpieza por si el modelo mete texto antes del JSON
                    clean_text = response.text.strip()
                    if clean_text.startswith("```json"):
                        clean_text = clean_text[7:-3]
                    
                    data = json.loads(clean_text)
                    st.session_state.datos_tecnicos.append(data)
                    
                    # 2. Renderizar respuesta
                    resp_texto = data["respuesta_paciente"]
                    deriv = data.get("derivacion", {})
                    st.write(resp_texto)
                    
                    map_url, map_lbl, is_emerg = None, None, False
                    if deriv.get("necesaria") and deriv.get("query_maps"):
                        map_lbl = "Ver Centros Cercanos"
                        map_url = generar_link_maps(deriv["query_maps"])
                        st.link_button(f"🗺️ {map_lbl}", map_url)
                        if data["traduccion_medica"]["gravedad"] in ["Alta", "Emergencia Vital"]:
                            st.error("🚨 ACUDA A URGENCIAS")
                            is_emerg = True
                    
                    st.session_state.historial_visual.append({
                        "role": "assistant", "content": resp_texto,
                        "map_url": map_url, "map_label": map_lbl, "is_emerg": is_emerg
                    })
                except Exception as e:
                    st.error(f"Error técnico: {e}")

# --- 7. BOTÓN DE INFORME (FINAL) ---
st.markdown("---")
col1, col2, col3 = st.columns([1, 6, 1])

with col2:
    if st.button("📄 PREPARAR INFORME CLÍNICO (PDF)", type="primary", use_container_width=True):
        if not st.session_state.datos_tecnicos:
            st.toast("⚠️ Hable con el doctor primero.")
        else:
            with st.spinner("Dr. Hipócrates está redactando el informe oficial..."):
                # A. Preparar el input para el Redactor
                historial_str = json.dumps(st.session_state.datos_tecnicos, indent=2)
                prompt_final = f"{PROMPT_INFORME_FINAL}\n\nDATOS DEL PACIENTE:\n{historial_str}"
                
                # B. Llamada a la API (Generación del texto)
                resp_informe = model_report.generate_content(prompt_final)
                texto_informe = resp_informe.text
                
                # C. Generación del PDF (Python FPDF)
                pdf_bytes = generar_pdf_desde_texto(texto_informe)
                
                # D. Mostrar resultados
                st.success("Informe generado.")
                
                # Vista previa (Expandible)
                with st.expander("Vista Previa del Texto"):
                    st.text(texto_informe)
                
                # Botón de Descarga
                st.download_button(
                    label="📥 DESCARGAR PDF PARA IMPRIMIR",
                    data=pdf_bytes,
                    file_name="Informe_Dr_Hipocrates.pdf",
                    mime="application/pdf",
                    use_container_width=True
                )
    
    st.caption("⚠️ Al cerrar esta pestaña, el historial y el informe se eliminarán permanentemente por seguridad.")
