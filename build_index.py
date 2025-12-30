from src.plagiarism.index_build import build_corpus_index

if __name__ == "__main__":
    build_corpus_index(
        corpus_dir="./corpus",
        index_dir="./src/plag_index"
    )
