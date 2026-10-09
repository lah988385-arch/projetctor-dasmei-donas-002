import os, asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv
from pathlib import Path
load_dotenv(Path(__file__).parent / '.env')

async def main():
    db = AsyncIOMotorClient(os.environ['MONGO_URL'])[os.environ['DB_NAME']]
    for col in ['apuracoes_importadas', 'mapas_pgmei', 'tentativas_consulta']:
        docs = await db[col].find({}, {'cnpj': 1, 'ano': 1, '_id': 0}).limit(5).to_list(5)
        print(col, '->', docs)

asyncio.run(main())
