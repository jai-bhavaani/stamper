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
    from PIL import Image
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=(page_width, page_height))

    for config in image_configs:
        img_stream = config['stream']
        x = config['x']
        y = config['y']
        target_width = config['width']

        # Ensure transparent PNGs preserve transparency inside ReportLab
        pil_img = Image.open(img_stream).convert("RGBA")
        img = ImageReader(pil_img)
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

        # Cache overlay pages by (page_width, page_height) to avoid redundant image embeddings
        overlay_cache = {}

        for page in reader.pages:
            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)
            size_key = (page_width, page_height)

            if size_key not in overlay_cache:
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
                        'x': 100, 
                        'y': 50,  
                        'width': 120 
                    })

                if image_configs:
                    overlay_io = create_overlay_layer(image_configs, page_width, page_height)
                    overlay_pdf = PdfReader(overlay_io)
                    overlay_cache[size_key] = overlay_pdf.pages[0]
                else:
                    overlay_cache[size_key] = None

            overlay_page = overlay_cache[size_key]
            if overlay_page:
                page.merge_page(overlay_page)

            writer.add_page(page)

        output_stream = io.BytesIO()
        writer.write(output_stream)
        output_stream.seek(0)
        return output_stream

    except Exception as e:
        st.error(f"An error occurred during PDF stamping: {e}")
        return None


# ==========================================
# HELPER: PDF COMPRESSION ENGINE
# ==========================================
def compress_pdf_bytes(pdf_bytes, target_size_mb=10.0, initial_quality=80):
    """
    Compresses PDF file bytes in-memory.
    1. Lossless pass: Compresses content streams and merges duplicate objects.
    2. Lossy image pass (only if size is still above target):
       Converts page images to RGB, optionally downscales them if they exceed 1500px,
       and replaces them with compressed JPEGs at different quality levels (80, 50, 30, 15).
    """
    from PIL import Image
    
    current_bytes = pdf_bytes
    current_size_mb = len(current_bytes) / (1024 * 1024)
    
    # --- Step 1: Lossless Compression ---
    try:
        reader = PdfReader(io.BytesIO(current_bytes))
        writer = PdfWriter()
        
        for page in reader.pages:
            writer.add_page(page)
            
        # Compress page content streams
        for page in writer.pages:
            try:
                page.compress_content_streams()
            except Exception:
                pass
                
        # Merge duplicate objects/images
        try:
            writer.compress_identical_objects(remove_duplicates=True)
        except Exception:
            pass
            
        out_buf = io.BytesIO()
        writer.write(out_buf)
        current_bytes = out_buf.getvalue()
        current_size_mb = len(current_bytes) / (1024 * 1024)
    except Exception as e:
        st.warning(f"Lossless compression step encountered an issue: {e}")
        
    # --- Step 2: Lossy Image Compression ---
    if current_size_mb > target_size_mb:
        # Try decreasing quality steps until target size is met or we run out of options
        for q in [initial_quality, 50, 30, 15]:
            try:
                reader = PdfReader(io.BytesIO(current_bytes))
                writer = PdfWriter()
                
                for page in reader.pages:
                    writer.add_page(page)
                
                has_images = False
                for page in writer.pages:
                    for img_obj in page.images:
                        has_images = True
                        try:
                            pil_img = img_obj.image
                            
                            # Preserve transparency when converting image modes
                            is_transparent = pil_img.mode in ('RGBA', 'LA') or (pil_img.mode == 'P' and 'transparency' in pil_img.info)
                            if is_transparent:
                                pil_img = pil_img.convert('RGBA')
                            else:
                                pil_img = pil_img.convert('RGB')
                            
                            # Downscale extremely large images to reduce size
                            width, height = pil_img.size
                            if width > 1500 or height > 1500:
                                ratio = min(1500 / width, 1500 / height)
                                new_size = (int(width * ratio), int(height * ratio))
                                pil_img = pil_img.resize(new_size, Image.Resampling.LANCZOS)
                                
                            img_obj.replace(pil_img, quality=q)
                        except Exception:
                            pass
                
                if not has_images:
                    break
                    
                out_buf = io.BytesIO()
                writer.write(out_buf)
                temp_bytes = out_buf.getvalue()
                temp_size_mb = len(temp_bytes) / (1024 * 1024)
                
                if temp_size_mb < current_size_mb:
                    current_bytes = temp_bytes
                    current_size_mb = temp_size_mb
                    
                if current_size_mb <= target_size_mb:
                    break
            except Exception:
                pass
                
    return current_bytes


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
    
    # Inject premium CSS
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap');
            
            /* Apply custom font */
            html, body, [class*="css"], .stApp, .stMarkdown, p, span, div, label, input, button {
                font-family: 'Outfit', sans-serif !important;
            }
            
            /* Header Accent Styling with Premium Gradients */
            .main-header {
                background: linear-gradient(135deg, #6366F1 0%, #A855F7 50%, #EC4899 100%);
                padding: 2.5rem;
                border-radius: 20px;
                color: white;
                margin-bottom: 2rem;
                text-align: center;
                box-shadow: 0 10px 30px -5px rgba(168, 85, 247, 0.4);
            }
            
            .main-header h1 {
                font-size: 2.5rem !important;
                font-weight: 700 !important;
                margin: 0 !important;
                color: white !important;
                text-shadow: 0 2px 10px rgba(0,0,0,0.15);
            }
            
            .main-header p {
                font-size: 1.1rem !important;
                margin-top: 0.8rem !important;
                opacity: 0.95;
                font-weight: 300 !important;
                color: white !important;
            }
            
            /* Premium Button Styling */
            div.stButton > button {
                background: linear-gradient(135deg, #6366F1 0%, #A855F7 100%) !important;
                color: white !important;
                font-weight: 600 !important;
                font-size: 1.05rem !important;
                border: none !important;
                padding: 0.75rem 2rem !important;
                border-radius: 12px !important;
                box-shadow: 0 4px 15px rgba(168, 85, 247, 0.25) !important;
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
                width: 100%;
                cursor: pointer;
            }
            
            div.stButton > button:hover {
                transform: translateY(-2px) !important;
                box-shadow: 0 8px 25px rgba(168, 85, 247, 0.45) !important;
                background: linear-gradient(135deg, #4F46E5 0%, #9333EA 100%) !important;
                color: white !important;
            }
            
            div.stButton > button:active {
                transform: translateY(1px) !important;
            }
            
            /* File Uploader Customizations */
            div[data-testid="stFileUploaderDropzone"] {
                border: 2px dashed rgba(168, 85, 247, 0.3) !important;
                border-radius: 12px !important;
                background-color: rgba(168, 85, 247, 0.02) !important;
            }
            
            div[data-testid="stFileUploaderDropzone"]:hover {
                border-color: #A855F7 !important;
                background-color: rgba(168, 85, 247, 0.05) !important;
            }
            
            /* Sidebar items */
            section[data-testid="stSidebar"] {
                border-right: 1px solid rgba(128,128,128,0.1) !important;
            }
        </style>
    """, unsafe_allow_html=True)

    # --- Sidebar Navigation ---
    st.sidebar.title("🛠️ Tools Menu")
    app_mode = st.sidebar.radio(
        "Select an Operation:",
        ["Authenticate Document (Stamp & Sign)", "Convert PDF to Word", "Compress PDF"]
    )
    
    # --- Route 1: Stamp & Sign UI ---
    if app_mode == "Authenticate Document (Stamp & Sign)":
        st.markdown("""
            <div class="main-header">
                <h1>📄 PDF Stamper & Signer</h1>
                <p>Upload a PDF alongside a stamp and signature. They will be dynamically overlayed without overlap.</p>
            </div>
        """, unsafe_allow_html=True)

        st.subheader("1. Upload Document")
        uploaded_pdf = st.file_uploader("Upload PDF File", type="pdf", key="auth_pdf")
        
        st.subheader("2. Upload Assets")
        col1, col2 = st.columns(2)
        with col1:
            uploaded_stamp = st.file_uploader("Company Stamp (Optional)", type=["png", "jpg", "jpeg"])
        with col2:
            uploaded_sig = st.file_uploader("Authorized Signature (Optional)", type=["png", "jpg", "jpeg"])

        if uploaded_pdf and (uploaded_stamp or uploaded_sig):
            st.subheader("3. Compression Settings (Optional)")
            with st.expander("⚙️ PDF Compression Settings", expanded=False):
                enable_compress = st.checkbox("Compress Output PDF", value=True, help="Reduces PDF file size to make it easier to share.")
                target_mb = st.slider("Target Maximum File Size (MB)", min_value=1.0, max_value=20.0, value=10.0, step=0.5, help="Attempts to keep the output size below this limit.")

            if st.button("Generate Authenticated PDF"):
                with st.spinner("Applying assets..."):
                    processed_pdf = process_pdf(uploaded_pdf, uploaded_stamp, uploaded_sig)
                    if processed_pdf:
                        original_size = len(processed_pdf.getvalue()) / (1024 * 1024)
                        
                        if enable_compress:
                            with st.spinner("Compressing output PDF..."):
                                pdf_data = processed_pdf.getvalue()
                                compressed_data = compress_pdf_bytes(pdf_data, target_size_mb=target_mb)
                                compressed_size = len(compressed_data) / (1024 * 1024)
                                processed_pdf = io.BytesIO(compressed_data)
                                
                                if compressed_size < original_size:
                                    st.info(f"🗜️ PDF size reduced from {original_size:.2f} MB to {compressed_size:.2f} MB")
                                else:
                                    st.info("PDF is already optimized and within size limits.")
                                    
                        st.success("Document generated successfully!")
                        st.download_button(
                            label="Download Final PDF",
                            data=processed_pdf,
                            file_name="authenticated_document.pdf",
                            mime="application/pdf"
                        )

    # --- Route 2: PDF to Word UI ---
    elif app_mode == "Convert PDF to Word":
        st.markdown("""
            <div class="main-header">
                <h1>📝 PDF to Word Converter</h1>
                <p>Extract structure, layout, and text content into a clean, editable Microsoft Word format.</p>
            </div>
        """, unsafe_allow_html=True)
        
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

    # --- Route 3: Compress PDF UI ---
    elif app_mode == "Compress PDF":
        st.markdown("""
            <div class="main-header">
                <h1>🗜️ PDF Size Optimizer</h1>
                <p>Reduce the file size of your PDF document using lossless structure optimization and lossy image compression.</p>
            </div>
        """, unsafe_allow_html=True)
        
        uploaded_pdf_to_compress = st.file_uploader("Upload PDF File to Compress", type="pdf", key="compress_pdf")
        
        if uploaded_pdf_to_compress:
            pdf_bytes = uploaded_pdf_to_compress.read()
            original_size = len(pdf_bytes) / (1024 * 1024)
            st.info(f"Original File Size: **{original_size:.2f} MB**")
            
            target_mb = st.slider(
                "Target Maximum File Size (MB)",
                min_value=1.0,
                max_value=20.0,
                value=10.0,
                step=0.5,
                help="The compressor will compress page contents and progressively reduce image quality to meet this target size."
            )
            
            if st.button("Compress PDF"):
                with st.spinner("Optimizing layout and compressing images..."):
                    compressed_data = compress_pdf_bytes(pdf_bytes, target_size_mb=target_mb)
                    compressed_size = len(compressed_data) / (1024 * 1024)
                    
                    if compressed_size < original_size:
                        st.success(f"Compression successful! Reduced by **{((original_size - compressed_size)/original_size)*100:.1f}%**")
                        st.write(f"Compressed Size: **{compressed_size:.2f} MB** (Original: **{original_size:.2f} MB**)")
                        st.balloons()
                        
                        original_name = uploaded_pdf_to_compress.name.replace(".pdf", "")
                        st.download_button(
                            label="Download Compressed PDF",
                            data=compressed_data,
                            file_name=f"{original_name}_compressed.pdf",
                            mime="application/pdf"
                        )
                    else:
                        st.warning("Could not compress the PDF further. It is already optimized and below your target size.")
                        st.download_button(
                            label="Download Output PDF",
                            data=compressed_data,
                            file_name=f"{uploaded_pdf_to_compress.name}",
                            mime="application/pdf"
                        )

if __name__ == "__main__":
    main()