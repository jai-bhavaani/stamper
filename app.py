import streamlit as st
import io
import os
import tempfile
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from pdf2docx import Converter

# ==========================================
# TOOL 1: STAMP & SIGNATURE ENGINE
# ==========================================
def create_overlay_layer(image_configs, page_width, page_height):
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=(page_width, page_height))

    for config in image_configs:
        img_stream = config['stream']
        x = config['x']
        y = config['y']
        target_width = config['width']

        img = ImageReader(img_stream)
        img_width, img_height = img.getSize()
        
        aspect = img_height / float(img_width)
        display_height = target_width * aspect

        can.drawImage(img, x, y, width=target_width, height=display_height, mask='auto')

    can.save()
    packet.seek(0)
    return packet

def process_pdf(pdf_file, stamp_file, sig_file):
    try:
        reader = PdfReader(pdf_file)
        writer = PdfWriter()

        stamp_bytes = stamp_file.read() if stamp_file else None
        sig_bytes = sig_file.read() if sig_file else None

        for page in reader.pages:
            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)

            image_configs = []
            
            if stamp_bytes:
                image_configs.append({
                    'stream': io.BytesIO(stamp_bytes),
                    'x': 50,  
                    'y': 50,   
                    'width': 100 
                })
                
            if sig_bytes:
                image_configs.append({
                    'stream': io.BytesIO(sig_bytes),
                    'x': 200, 
                    'y': 50,  
                    'width': 120 
                })

            if image_configs:
                overlay_io = create_overlay_layer(image_configs, page_width, page_height)
                overlay_pdf = PdfReader(overlay_io)
                page.merge_page(overlay_pdf.pages[0])

            writer.add_page(page)

        output_stream = io.BytesIO()
        writer.write(output_stream)
        output_stream.seek(0)
        return output_stream

    except Exception as e:
        st.error(f"An error occurred during PDF stamping: {e}")
        return None


# ==========================================
# TOOL 2: PDF TO WORD ENGINE
# ==========================================
def convert_pdf_to_word(uploaded_file):
    """
    Saves the Streamlit uploaded file to a temporary system file,
    converts it using pdf2docx, reads it back into memory, and cleans up.
    """
    # Create temporary file paths
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as temp_pdf:
        temp_pdf.write(uploaded_file.read())
        pdf_path = temp_pdf.name
        
    docx_path = pdf_path.replace(".pdf", ".docx")

    try:
        # Perform the conversion
        cv = Converter(pdf_path)
        cv.convert(docx_path)
        cv.close()

        # Read the resulting Word document into a memory buffer
        with open(docx_path, "rb") as docx_file:
            docx_bytes = docx_file.read()
            
        return docx_bytes

    except Exception as e:
        st.error(f"Conversion failed: {e}")
        return None
        
    finally:
        # PACTICALITY: ALWAYS clean up temp files to prevent storage bloat
        if os.path.exists(pdf_path):
            os.remove(pdf_path)
        if os.path.exists(docx_path):
            os.remove(docx_path)


# ==========================================
# MAIN DASHBOARD (UI ROUTING)
# ==========================================
def main():
    st.set_page_config(page_title="PDF Swiss Army Knife", layout="centered")
    
    # --- Sidebar Navigation ---
    st.sidebar.title("🛠️ Tools Menu")
    app_mode = st.sidebar.radio(
        "Select an Operation:",
        ["Authenticate Document (Stamp & Sign)", "Convert PDF to Word"]
    )
    
    # --- Route 1: Stamp & Sign UI ---
    if app_mode == "Authenticate Document (Stamp & Sign)":
        st.title("📄 PDF stamper")
        st.write("Upload a PDF alongside a Stamp and/or a Signature. They will be placed without overlapping.")

        st.subheader("1. Upload Document")
        uploaded_pdf = st.file_uploader("Upload PDF File", type="pdf", key="auth_pdf")
        
        st.subheader("2. Upload Assets")
        col1, col2 = st.columns(2)
        with col1:
            uploaded_stamp = st.file_uploader("Company Stamp (Optional)", type=["png", "jpg", "jpeg"])
        with col2:
            uploaded_sig = st.file_uploader("Authorized Signature (Optional)", type=["png", "jpg", "jpeg"])

        if uploaded_pdf and (uploaded_stamp or uploaded_sig):
            if st.button("Generate Authenticated PDF"):
                with st.spinner("Applying assets..."):
                    processed_pdf = process_pdf(uploaded_pdf, uploaded_stamp, uploaded_sig)
                    if processed_pdf:
                        st.success("Document generated successfully!")
                        st.download_button(
                            label="Download Final PDF",
                            data=processed_pdf,
                            file_name="authenticated_document.pdf",
                            mime="application/pdf"
                        )

    # --- Route 2: PDF to Word UI ---
    elif app_mode == "Convert PDF to Word":
        st.title("📝 PDF to Word Converter")
        st.write("Extract text and layout from a PDF into an editable Microsoft Word (.docx) format.")
        
        uploaded_pdf_for_word = st.file_uploader("Upload PDF File to Convert", type="pdf", key="word_pdf")
        
        if uploaded_pdf_for_word:
            # We display a warning so the user's expectations are managed
            st.info("Note: Complex PDFs with heavy graphics or scanned images may not convert perfectly. Text-heavy documents work best.")
            
            if st.button("Convert to Word"):
                with st.spinner("Analyzing and converting document... (This may take a moment for large files)"):
                    word_bytes = convert_pdf_to_word(uploaded_pdf_for_word)
                    
                    if word_bytes:
                        st.success("Conversion successful!")
                        st.balloons() # Added a little flair for a long process!
                        
                        original_name = uploaded_pdf_for_word.name.replace(".pdf", "")
                        st.download_button(
                            label="Download Word Document",
                            data=word_bytes,
                            file_name=f"{original_name}_converted.docx",
                            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                        )

if __name__ == "__main__":
    main()