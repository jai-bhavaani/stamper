import streamlit as st
import io
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader

# --- 1. The Engine (Processing Logic) ---
def create_overlay_layer(image_configs, page_width, page_height):
    """
    Creates a transparent PDF page dynamically placing multiple images 
    based on their specific configuration coordinates.
    """
    packet = io.BytesIO()
    can = canvas.Canvas(packet, pagesize=(page_width, page_height))

    for config in image_configs:
        img_stream = config['stream']
        x = config['x']
        y = config['y']
        target_width = config['width']

        # Process the Image to preserve aspect ratio
        img = ImageReader(img_stream)
        img_width, img_height = img.getSize()
        
        aspect = img_height / float(img_width)
        display_height = target_width * aspect

        # Draw Image at assigned non-overlapping coordinates
        can.drawImage(img, x, y, width=target_width, height=display_height, mask='auto')

    can.save()
    packet.seek(0)
    return packet

def process_pdf(pdf_file, stamp_file, sig_file):
    try:
        reader = PdfReader(pdf_file)
        writer = PdfWriter()

        # Extract bytes once to reuse across multiple pages safely
        stamp_bytes = stamp_file.read() if stamp_file else None
        sig_bytes = sig_file.read() if sig_file else None

        for page in reader.pages:
            page_width = float(page.mediabox.width)
            page_height = float(page.mediabox.height)

            image_configs = []
            
            # --- ZONING LOGIC ---
            # Define specific X, Y coordinates to prevent overlap
            
            if stamp_bytes:
                image_configs.append({
                    'stream': io.BytesIO(stamp_bytes),
                    'x': 50,        # Left margin
                    'y': 50,        # Bottom margin
                    'width': 100    # Ends at x = 150
                })
                
            if sig_bytes:
                image_configs.append({
                    'stream': io.BytesIO(sig_bytes),
                    'x': 150,       # Starts past the stamp's end (150) + 50 buffer
                    'y': 50,        # Aligned horizontally with stamp
                    'width': 120    # Signatures are typically slightly wider
                })

            # Only create and merge an overlay if files were actually uploaded
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
        st.error(f"An error occurred during PDF processing: {e}")
        return None

# --- 2. The Dashboard ---
def main():
    st.set_page_config(page_title="PDF Stamper & Signer", layout="centered")
    st.title("📄 PDF Document Authenticator")
    st.write("Upload a PDF alongside a Stamp and/or a Signature. They will be placed automatically without overlapping.")

    # A. Inputs
    st.subheader("1. Upload Document")
    uploaded_pdf = st.file_uploader("Upload PDF File", type="pdf")
    
    st.subheader("2. Upload Assets")
    col1, col2 = st.columns(2)
    with col1:
        uploaded_stamp = st.file_uploader("Company Stamp (Optional)", type=["png", "jpg", "jpeg"])
    with col2:
        uploaded_sig = st.file_uploader("Authorized Signature (Optional)", type=["png", "jpg", "jpeg"])

    # B. Processing
    if uploaded_pdf and (uploaded_stamp or uploaded_sig):
        st.info("Assets loaded. Ready to process.")
        
        if st.button("Generate Authenticated PDF"):
            with st.spinner("Processing document..."):
                processed_pdf = process_pdf(uploaded_pdf, uploaded_stamp, uploaded_sig)
                
                if processed_pdf:
                    st.success("Document generated successfully!")
                    st.download_button(
                        label="Download Final PDF",
                        data=processed_pdf,
                        file_name="authenticated_document.pdf",
                        mime="application/pdf"
                    )

if __name__ == "__main__":
    main()