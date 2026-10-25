from langchain_ollama import OllamaEmbeddings


EMBEDDING_MODEL = "nomic-embed-text"


embeddings = OllamaEmbeddings(
    model=EMBEDDING_MODEL
)


if __name__ == "__main__":

    text = "A professional website can help a local business attract customers."

    vector = embeddings.embed_query(text)

    print("\n========== EMBEDDING TEST ==========\n")

    print("Text:")
    print(text)

    print("\nVector length:")
    print(len(vector))

    print("\nFirst 10 values:")
    print(vector[:10])
