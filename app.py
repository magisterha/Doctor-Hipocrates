import streamlit as st
import google.generativeai as genai
import json
import urllib.parse
from datetime import datetime
from fpdf import FPDF

# --- 1. CONFIGURACIÓN E INICIALIZACIÓN ---
try:
    genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
except KeyError:
    st.error("⚠️ Error Crítico: No se encontró la API Key. Configura el archivo .streamlit/secrets.toml")
    st.stop()

# Configuración para Gemini 2.5 Flash Lite
generation_config_chat = {
    "temperature": 0.3, 
    "top_p": 0.95,
    "response_mime_type": "application/json", # Chat siempre responde JSON
}

# Modelos independientes
model_chat = genai.GenerativeModel("gemini-2.5-flash-lite", generation_config=generation_config_chat)
model_report = genai.GenerativeModel("gemini-2.5-flash-lite") # Sin JSON forzado para el texto del informe

# --- 2. PROMPTS DEL SISTEMA ---

PROMPT_TRIAJE = """
# ROL: Dr. Hipócrates (IA de Triaje Médico)
Tu misión es escuchar, calmar y estructurar síntomas. Responde SIEMPRE con un JSON válido.

# PROTOCOLO
1. L_User: Responde en el idioma del paciente.
2. L_Target: Usa Inglés Médico Internacional para los datos técnicos.
3. Derivación: Genera 'query_maps' para buscar ayuda física (Pharmacy, Clinic, Hospital Emergency).

# FORMATO JSON OBLIGATORIO
{
  "traduccion_medica": { "motivo": "...", "sintomas": ["..."], "gravedad": "Baja/Media/Alta/Emergencia Vital" },
  "derivacion": { "necesaria": true/false, "query_maps": "..." },
  "respuesta_paciente": "..."
}
"""

PROMPT_INFORME = """
Actúa como Consultor Médico Senior. Redacta una CARTA DE DERIVACIÓN CLÍNICA (Referral Letter) basada en los datos JSON adjuntos.
Objetivo: Comunicación rápida entre triaje y médico especialista.
Idioma: Inglés Médico Internacional (salvo que el contexto exija local).
Estructura:
1. Header (Date, ID).
2. Chief Complaint.
3. History of Present Illness (HPI).
4. Clinical Assessment & Urgency.
5. Disclaimer (AI generated).
"""

# --- 3. CLASES Y FUNCIONES AUXILIARES ---

class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 14)
        self.cell(0, 10, 'Dr. Hipocrates AI - Informe de Derivacion', 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Pagina {self.page_no()}', 0, 0, 'C')

def generar_pdf_desde_texto(texto_informe):
    pdf = PDF()
    pdf.add_page()
    pdf.set_font("Arial", size=11)
    # Codificación compatible con caracteres latinos básicos
    texto_limpio = texto_informe.encode('latin-1', 'replace').decode('latin-1')
    pdf.multi_cell(0, 7, texto_limpio)
    return pdf.output(dest='S').encode('latin-1')

def generar_link_maps(query):
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(query)

# --- 4. INTERFAZ DE USUARIO (UI) ---

st.set_page_config(page_title="Dr. Hipócrates", page_icon="⚕️")
st.title("⚕️ Dr. Hipócrates")
st.warning("⚠️ **AVISO:** Esta herramienta es una IA de asistencia. NO sustituye al criterio médico profesional. En caso de duda grave, llame a emergencias.")

# Gestión de Estado (Session State)
if "chat" not in st.session_state:
    # Iniciamos el chat inyectando el prompt de sistema
    st.session_state.chat = model_chat.start_chat(history=[
        {"role": "user", "parts": "Instrucciones de sistema: " + PROMPT_TRIAJE},
        {"role": "model", "parts": json.dumps({"respuesta_paciente": "Entendido. Soy el Dr. Hipócrates."})}
    ])
if "historial_visual" not in st.session_state:
    st.session_state.historial_visual = [{"role": "assistant", "content": "Buenos días. Soy el Dr. Hipócrates. Por favor, descríbame sus síntomas."}]
if "datos_tecnicos" not in st.session_state:
    st.session_state.datos_tecnicos = []

# --- 5. BUCLE DE CHAT Y RENDERIZADO (CORREGIDO) ---

chat_container = st.container()

with chat_container:
    for msg in st.session_state.historial_visual:
        with st.chat_message(msg["role"]):
            st.write(msg["content"])
            
            # --- CORRECCIÓN AQUÍ ---
            # Usamos .get() para verificar que EXISTA un valor real (y no sea None)
            if msg.get("map_url"):
                label = msg.get("map_label", "Ver Mapa")
                st.link_button(f"📍 {label}", msg["map_url"])
                
                if msg.get("is_emerg"):
                    st.error("🚨 POSIBLE EMERGENCIA VITAL")

# --- 6. PROCESAMIENTO DEL INPUT ---

user_input = st.chat_input("Escriba aquí sus síntomas...")

if user_input:
    # 1. Mostrar mensaje usuario
    st.session_state.historial_visual.append({"role": "user", "content": user_input})
    with chat_container:
        st.chat_message("user").write(user_input)
    
    # 2. Procesar IA
    with chat_container:
        with st.chat_message("assistant"):
            with st.spinner("Dr. Hipócrates analizando..."):
                try:
                    response = st.session_state.chat.send_message(user_input)
                    
                    # Limpieza defensiva del JSON (por si el modelo añade markdown)
                    text_resp = response.text.strip()
                    if text_resp.startswith("```json"):
                        text_resp = text_resp[7:-3]
                    
                    data = json.loads(text_resp)
                    st.session_state.datos_tecnicos.append(data) # Guardar dato técnico
                    
                    # Extraer datos visuales
                    resp_paciente = data["respuesta_paciente"]
                    deriv = data.get("derivacion", {})
                    
                    st.write(resp_paciente)
                    
                    # Lógica de Mapa
                    map_url = None
                    map_lbl = None
                    is_emerg = False
                    
                    if deriv.get("necesaria") and deriv.get("query_maps"):
                        map_lbl = "Ver Centros Recomendados"
                        map_url = generar_link_maps(deriv["query_maps"])
                        
                        st.link_button(f"🗺️ {map_lbl}", map_url)
                        
                        # Alerta visual si es grave
                        gravedad = data.get("traduccion_medica", {}).get("gravedad", "Baja")
                        if gravedad in ["Alta", "Emergencia Vital"]:
                            st.error("🚨 RECOMENDACIÓN: ACUDIR A URGENCIAS")
                            is_emerg = True
                    
                    # Guardar en historial visual
                    st.session_state.historial_visual.append({
                        "role": "assistant",
                        "content": resp_paciente,
                        "map_url": map_url,
                        "map_label": map_lbl,
                        "is_emerg": is_emerg
                    })
                    
                except Exception as e:
                    st.error(f"Error de conexión o formato: {e}")

# --- 7. ZONA DE INFORME (FINAL DE PÁGINA) ---
st.markdown("---")
col1, col2, col3 = st.columns([1, 6, 1])

with col2:
    if st.button("📄 PREPARAR INFORME MÉDICO (PDF)", type="primary", use_container_width=True):
        if not st.session_state.datos_tecnicos:
            st.toast("⚠️ Aún no hay datos suficientes para un informe.")
        else:
            with st.spinner("Redactando informe clínico oficial..."):
                try:
                    # Preparar prompt para el redactor
                    datos_str = json.dumps(st.session_state.datos_tecnicos, indent=2)
                    prompt_final = f"{PROMPT_INFORME}\n\nDATOS DEL PACIENTE:\n{datos_str}"
                    
                    # Generar texto
                    resp_informe = model_report.generate_content(prompt_final)
                    texto_final = resp_informe.text
                    
                    # Generar PDF
                    pdf_bytes = generar_pdf_desde_texto(texto_final)
                    
                    st.success("✅ Informe generado correctamente.")
                    
                    # Botón de descarga
                    st.download_button(
                        label="📥 DESCARGAR PDF",
                        data=pdf_bytes,
                        file_name="Informe_Dr_Hipocrates.pdf",
                        mime="application/pdf",
                        use_container_width=True
                    )
                    
                    with st.expander("Vista previa del texto"):
                        st.text(texto_final)
                        
                except Exception as e:
                    st.error(f"Error al generar el informe: {e}")

    st.caption("🔒 Nota de Privacidad: Al cerrar esta pestaña, todo el historial médico se eliminará permanentemente.")
