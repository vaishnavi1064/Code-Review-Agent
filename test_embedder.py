from src.models import IngestConfig, SupportedLanguage
from src.github_ingestor import ingest_repo
from src.embedder import build_index, search_similar

config = IngestConfig(
    repo_url='https://github.com/vaishnavi1064/Retail-Inventory-Order-Fulfillment-System',
    selected_languages=[SupportedLanguage.JAVA]
)

print('Step 1: Fetching files from GitHub...')
files, skipped = ingest_repo(config)
print(f'Fetched {len(files)} files')

print()
print('Step 2: Building FAISS index...')
index, metadata = build_index(files, config.repo_url)

print()
print('Step 3: Searching for similar code...')
results = search_similar(
    query_code='public void addProduct(String name, int quantity) { inventory.put(name, quantity); }',
    repo_url=config.repo_url,
    top_k=3
)

print()
print('--- TOP 3 SIMILAR FUNCTIONS FROM YOUR REPO ---')
for i, r in enumerate(results):
    print(f'{i+1}. {r[chr(34) + "chunk_id" + chr(34)]}')
    print(f'   Similarity: {r[chr(34) + "similarity_score" + chr(34)]}')
    print(f'   Preview: {r[chr(34) + "preview" + chr(34)][:100]}')
    print()
