from src.models import IngestConfig, SupportedLanguage
from src.embedder import search_similar

results = search_similar(
    query_code='public void addProduct(String name, int quantity) { inventory.put(name, quantity); }',
    repo_url='https://github.com/vaishnavi1064/Retail-Inventory-Order-Fulfillment-System',
    top_k=3
)

print('--- TOP 3 SIMILAR FUNCTIONS FROM YOUR REPO ---')
for i, r in enumerate(results):
    chunk_id = r.get('chunk_id', 'unknown')
    similarity = r.get('similarity_score', 0)
    preview = r.get('preview', '')[:120]
    print(f'{i+1}. {chunk_id}')
    print(f'   Similarity : {similarity}')
    print(f'   Preview    : {preview}')
    print()
