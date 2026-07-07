import os
import re
import fitz
import streamlit as st
from openai import AzureOpenAI
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import SearchIndex, SimpleField, SearchableField
from azure.core.credentials import AzureKeyCredential
from dotenv import load_dotenv

load_dotenv()

search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
search_key = os.getenv("AZURE_SEARCH_KEY")
index_name = os.getenv("AZURE_SEARCH_INDEX")

openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    api_version=os.getenv("AZURE_OPENAI_API_VERSION")
)

def create_index():
    index_client = SearchIndexClient(
        endpoint=search_endpoint,
        credential=AzureKeyCredential(search_key)
    )

    fields = [
        SimpleField(name="id", type="Edm.String", key=True),
        SearchableField(name="content", type="Edm.String"),
        SearchableField(name="source", type="Edm.String", filterable=True)
    ]

    index = SearchIndex(name=index_name, fields=fields)
    index_client.create_or_update_index(index)

if "index_created" not in st.session_state:
    try:
        create_index()
        st.session_state.index_created = True
    except:
        st.session_state.index_created = True

#Streamlit UI
st.title("Smart AI RAG")
st.caption("Upload up to 2 PDFs, Ask anything from them")

st.subheader("Step 1: Upload your PDFs")
uploaded_files = st.file_uploader("Choose PDF files (max 2)", type="pdf", accept_multiple_files=True)

if uploaded_files:
    uploaded_files = uploaded_files[:2]

    search_client = SearchClient(
        endpoint=search_endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(search_key)
    )

    total_chunks = 0
    for uploaded_file in uploaded_files:
        doc = fitz.open(stream=uploaded_file.read(), filetype="pdf")
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()

        # Split into chunks
        chunks = [text[i:i+1000] for i in range(0, len(text), 1000)]

        # Unique id per file so multiple PDFs don't overwrite each other
        safe_name = re.sub(r"[^A-Za-z0-9_\-=]", "_", uploaded_file.name)
        documents = [{"id": f"{safe_name}_{i}", "content": chunk, "source": uploaded_file.name} for i, chunk in enumerate(chunks)]
        if documents:
            search_client.upload_documents(documents)
            total_chunks += len(documents)

    file_names = ", ".join(f.name for f in uploaded_files)
    st.success(f"✅ Uploaded {total_chunks} chunks from {file_names}")

    # Step 2 - Ask a question
    st.subheader("Step 2 — Ask a question")
    question = st.text_input("Type your question here...")

    col1, col2 = st.columns([1, 1])
    ask_clicked = col1.button("Ask")
    clear_clicked = col2.button("Clear")

    if clear_clicked:
        try:
            index_client = SearchIndexClient(
                endpoint=search_endpoint,
                credential=AzureKeyCredential(search_key)
            )
            index_client.delete_index(index_name)
            create_index()
            st.success("Index cleared. Please re-upload your PDFs.")
        except Exception as e:
            st.error(f"Could not clear index: {e}")

    if ask_clicked:
        # Search Azure AI Search (ranked by relevance across both documents)
        results = list(search_client.search(question, top=3))
        context = " ".join([f"[Source: {r.get('source') or 'unknown'}] {r['content']}" for r in results])

        # Ask Azure OpenAI
        response = openai_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": f"Answer only from this document, using whichever source is most relevant to the question: {context}"},
                {"role": "user", "content": question}
            ],
            max_completion_tokens=2000
        )

        st.write("**Answer:**")
        st.write(response.choices[0].message.content)