import os
import asyncio
from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

load_dotenv()

async def verify_gemini():
    print("--- Verifying Gemini API Access ---")
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("❌ GOOGLE_API_KEY not found in environment")
        return

    print(f"✅ GOOGLE_API_KEY found (starts with {api_key[:5]}...)")

    # 1. Test Chat Model (gemini-2.5-flash)
    print("\n[1/2] Testing Chat Model: gemini-2.5-flash")
    try:
        llm = ChatGoogleGenerativeAI(
            model="gemini-2.5-flash",
            google_api_key=api_key,
            temperature=0
        )
        response = await llm.ainvoke("Hello, simply say 'Connected!' if you can hear me.")
        print(f"✅ Chat Success: {response.content}")
    except Exception as e:
        print(f"❌ Chat Failed: {str(e)}")

    # 2. Test Embeddings (models/gemini-embedding-001)
    print("\n[2/2] Testing Embeddings: models/gemini-embedding-001")
    try:
        embeddings = GoogleGenerativeAIEmbeddings(
            model="models/gemini-embedding-001",
            google_api_key=api_key
        )
        vec = await embeddings.aembed_query("Test embedding")
        print(f"✅ Embeddings Success. Vector length: {len(vec)}")
        if len(vec) != 3072:
             print(f"⚠️ Warning: Expected 3072 dimensions, got {len(vec)}")
    except Exception as e:
        print(f"❌ Embeddings Failed: {str(e)}")

if __name__ == "__main__":
    asyncio.run(verify_gemini())
