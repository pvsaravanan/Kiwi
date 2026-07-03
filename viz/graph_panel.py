import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network

from sentinel.cognee_client import CogneeClient
from sentinel.config import load_settings

st.set_page_config(page_title="Sentinel — CI Failure Memory", layout="wide")
st.title("Sentinel — CI Failure Memory (Cognee Cloud)")

client = CogneeClient()
settings = load_settings()

left, right = st.columns([1, 2])

with left:
    st.header("Recall")
    query = st.text_area("Ask memory:", placeholder="A test failed with a duplicate charge…")
    if st.button("Recall", type="primary") and query:
        with st.spinner("Querying Cognee…"):
            hits = client.recall(query, dataset=settings.dataset)
        st.session_state["hits"] = hits
    for hit in st.session_state.get("hits", []):
        st.markdown(hit.get("text", ""))

with right:
    st.header(f"Memory graph — dataset '{settings.dataset}'")
    datasets = client.datasets()
    match = next((d for d in datasets if d.get("name") == settings.dataset), None)
    if not match:
        st.info("Dataset not found yet — run `uv run sentinel seed` first.")
    else:
        graph = client.graph(match["id"])
        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        net = Network(height="600px", width="100%", bgcolor="#111", font_color="#eee")
        for n in nodes:
            net.add_node(str(n.get("id")),
                         label=str(n.get("label") or n.get("name") or n.get("id"))[:40], size=12)
        for e in edges:
            src, dst = str(e.get("source")), str(e.get("target"))
            if src and dst:
                net.add_edge(src, dst, label=str(e.get("label") or "")[:20])
        components.html(net.generate_html(), height=620)
        st.caption(f"{len(nodes)} nodes, {len(edges)} edges — live from Cognee Cloud")
