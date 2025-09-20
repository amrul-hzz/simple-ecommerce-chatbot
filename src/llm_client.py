from dotenv import load_dotenv
import os
import requests
import json

load_dotenv()

OLLAMA_API_URL = os.getenv("OLLAMA_API_URL")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")

# Try to use LangChain Ollama wrapper if available
USE_LANGCHAIN = False
try:
    from langchain import LLMChain, PromptTemplate
    from langchain.llms import Ollama
    USE_LANGCHAIN = True
except Exception:
    USE_LANGCHAIN = False

def _prompt_with_history(last_messages, user_message):
    history_text = ""
    for m in last_messages:
        history_text += f"{m['role'].capitalize()}: {m['content']}\n"

    prompt = (
        "Anda adalah asisten customer support e-commerce yang ramah dan membantu. Anda berkomunikasi dalam bahasa Indonesia.\n"
        "Anda memiliki akses ke tools berikut:\n"
        "1. get_order_status(order_id) → mengembalikan status pengiriman pesanan.\n"
        "2. get_warranty_info(product_id ATAU nama_produk) → mengembalikan kebijakan garansi untuk produk.\n"
        "3. get_product_info(product_id ATAU nama_produk) → mengembalikan deskripsi produk, kelebihan dan kekurangan.\n\n"
        
        "Produk yang tersedia di toko kami:\n"
        "- Headphone Wireless (ID: P123)\n"
        "- Smartphone X (ID: P234)\n"
        "- Gaming Laptop Pro (ID: P345)\n\n"
        
        "ATURAN DETEKSI INTENT (analisis pesan user dengan cermat):\n\n"
        
        "1. DETEKSI ORDER/PESANAN:\n"
        "   - Jika ada kode ORD (misal: ORD12345, ORD23456) → get_order_status dengan kode tersebut\n"
        "   - Kata kunci: 'pesanan', 'order', 'status', 'dimana', 'kapan sampai', 'tracking', 'pengiriman'\n"
        "   - Frasa: 'pesanan saya', 'status pesanan', 'dimana pesanan', 'order saya'\n"
        "   - Jika tidak ada kode ORD tapi menanyakan pesanan → get_order_status dengan input kosong\n\n"
        
        "2. DETEKSI GARANSI:\n"
        "   - Kata kunci: 'garansi', 'warranty', 'jaminan', 'klaim', 'rusak', 'bermasalah'\n"
        "   - Frasa: 'garansi produk', 'cara klaim', 'masa garansi', 'warranty info'\n"
        "   - Jika menyebut produk (ID/nama) + garansi → get_warranty_info dengan produk tersebut\n"
        "   - Jika hanya 'garansi' tanpa produk spesifik:\n"
        "     * Cek riwayat chat untuk produk yang disebutkan sebelumnya\n"
        "     * Atau cek pesanan terakhir user untuk mendapat produk\n"
        "     * Jika tidak ada, tanya produk mana\n\n"
        
        "3. DETEKSI INFO PRODUK:\n"
        "   - Kata kunci: 'kelebihan', 'kekurangan', 'pros', 'cons', 'deskripsi', 'detail', 'spesifikasi'\n"
        "   - Kata: 'tentang', 'info', 'informasi', 'review', 'bagaimana', 'seperti apa'\n"
        "   - Frasa: 'apa kelebihan', 'gimana produk', 'ceritain tentang', 'pengen tau'\n"
        "   - Deteksi nama produk dalam berbagai variasi:\n"
        "     * 'headphone', 'wireless headphone', 'earphone'\n"
        "     * 'smartphone', 'hp', 'ponsel', 'handphone'\n"
        "     * 'laptop', 'gaming laptop', 'laptop gaming'\n\n"
        
        "4. KONTEKS CERDAS:\n"
        "   - Gunakan riwayat percakapan untuk memahami konteks\n"
        "   - Jika user bertanya 'garansinya?' setelah membahas produk, asumsikan produk yang sama\n"
        "   - Jika user bertanya 'pesananku?' tanpa menyebut kode, cari pesanan terakhir\n"
        "   - Ingat produk yang sedang dibahas dalam percakapan\n\n"
        
        "5. SMART MATCHING:\n"
        "   - 'headphone'/'earphone' → Headphone Wireless\n"
        "   - 'hp'/'smartphone'/'ponsel' → Smartphone X  \n"
        "   - 'laptop'/'gaming' → Gaming Laptop Pro\n"
        "   - Bisa menggunakan ID (P123) atau nama partial\n\n"
        
        "Riwayat percakapan (gunakan untuk konteks):\n"
        f"{history_text}\n"
        f"User: {user_message}\n\n"
        
        "Output format:\n"
        "1. JSON action di baris pertama: {\"action\":\"nama_tool\",\"action_input\":\"parameter\"}\n"
        "2. Balasan natural dalam bahasa Indonesia\n\n"
        
        "Contoh:\n"
        '{"action":"get_order_status","action_input":"ORD12345"}\nSaya cek status pesanan ORD12345 dulu ya.\n\n'
        '{"action":"get_order_status","action_input":""}\nSaya cek pesanan terakhir Anda.\n\n'
        '{"action":"get_warranty_info","action_input":"headphone wireless"}\nBerikut info garansi untuk Headphone Wireless.\n\n'
        '{"action":"get_product_info","action_input":"smartphone"}\nIni detail lengkap Smartphone X.\n\n'
        '{"action":"none","action_input":""}\nAda yang bisa saya bantu?\n\n'
    )

    return prompt

def call_ollama_http(prompt, temperature=0.0, max_tokens=512):
    url = OLLAMA_API_URL.rstrip("/") + "/api/generate"
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    try:
        r = requests.post(url, json=payload, timeout=60, stream=True)
        r.raise_for_status()
        output = ""
        for line in r.iter_lines():
            if not line:
                continue
            data = json.loads(line.decode("utf-8"))
            if "response" in data:
                output += data["response"]
            if data.get("done", False):
                break
        return output.strip()
    except Exception as e:
        raise RuntimeError(f"Ollama HTTP call failed: {e}")

class LLMClient:
    def __init__(self):
        self.use_langchain = USE_LANGCHAIN
        if self.use_langchain:
            try:
                self.llm = Ollama(model=OLLAMA_MODEL, temperature=0.0)
                self.template = "{prompt}"
                self.prompt = PromptTemplate(input_variables=["prompt"], template=self.template)
                self.chain = LLMChain(llm=self.llm, prompt=self.prompt)
            except Exception:
                self.use_langchain = False

    def ask(self, last_messages, user_message):
        prompt = _prompt_with_history(last_messages, user_message)
        if self.use_langchain:
            resp = self.chain.run(prompt=prompt)
            return resp
        else:
            return call_ollama_http(prompt)