from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from src.db_model import AsyncSessionLocal, Order, Product
from src.db_seed import init_database, create_tables, seed_database
from src.db_tool import (
    persist_message,
    get_last_n_messages,
    get_all_messages_for_user,
    get_order_status,
    get_user_order_status,
    get_latest_order_for_user,
    get_all_orders_for_user,
    get_product_info,
    search_product_by_name,
    get_all_products,
    get_warranty_info,
    get_all_warranties
)
from src.llm_client import LLMClient
import json
import sqlalchemy
import re
import time

app = FastAPI(title="E-commerce Support Chatbot")

llm = LLMClient()

# Pydantic models
class ChatRequest(BaseModel):
    user_id: str
    message: str

class ChatResponse(BaseModel):
    reply: str
    tool_called: Optional[str] = None
    tool_output: Optional[Dict[str, Any]] = None

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    await init_database()

def try_parse_json_action(text: str):
    """Find the first JSON object in text and parse it. Returns dict or None."""
    try:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidate = text[start : end + 1]
            j = json.loads(candidate)
            return j
    except Exception:
        return None
    return None

# Cache for product patterns to avoid repeated DB queries
_product_patterns_cache = None
_cache_timestamp = None

async def get_product_patterns():
    """Generate product name patterns dynamically from database with caching."""
    global _product_patterns_cache, _cache_timestamp
    import time
    
    # Cache for 5 minutes
    if (_product_patterns_cache is not None and 
        _cache_timestamp is not None and 
        time.time() - _cache_timestamp < 300):
        return _product_patterns_cache
    
    async with AsyncSessionLocal() as session:
        q = await session.execute(sqlalchemy.select(Product))
        products = q.scalars().all()
        
        patterns = []
        product_mapping = {}
        
        for product in products:
            # Add exact product name
            exact_pattern = rf"\b({re.escape(product.name.lower())})\b"
            patterns.append(exact_pattern)
            product_mapping[exact_pattern] = product.name
            
            # Add individual significant words (skip common words)
            name_words = product.name.lower().split()
            significant_words = [word for word in name_words if len(word) > 3]
            
            for word in significant_words:
                word_pattern = rf"\b({re.escape(word)})\b"
                patterns.append(word_pattern)
                product_mapping[word_pattern] = product.name
        
        _product_patterns_cache = (patterns, product_mapping)
        _cache_timestamp = time.time()
        
        return _product_patterns_cache

async def extract_patterns(message: str):
    """Extract order IDs, product IDs, and product names from message."""
    patterns = {
        "order_id": re.search(r"(ORD\d+)", message, re.I),
        "product_id": re.search(r"(P\d+)", message, re.I),
        "product_name": None,
        "matched_product": None
    }    

    pattern_list, product_mapping = await get_product_patterns()
    
    for pattern in pattern_list:
        match = re.search(pattern, message, re.I)
        if match:
            patterns["product_name"] = match
            patterns["matched_product"] = product_mapping.get(pattern)
            break
    
    return patterns

def determine_fallback_action(message: str, patterns: dict):
    """Determine action based on patterns and keywords when LLM fails."""
    # Order queries
    if patterns["order_id"]:
        return {"action": "get_order_status", "action_input": patterns["order_id"].group(1)}
    
    if re.search(r"\b(pesanan saya|status pesanan|dimana pesanan|my order|order status)\b", message, re.I):
        return {"action": "get_order_status", "action_input": ""}
    
    # Warranty queries
    if re.search(r"\b(garansi|warranty|guarantee|jaminan)\b", message, re.I):
        if patterns["product_id"]:
            return {"action": "get_warranty_info", "action_input": patterns["product_id"].group(1)}
        elif patterns["product_name"]:
            return {"action": "get_warranty_info", "action_input": patterns["product_name"].group(1)}
    
    # Product info queries
    if re.search(r"\b(kelebihan|kekurangan|deskripsi|detail|pros|cons|description|about|info)\b", message, re.I):
        if patterns["product_id"]:
            return {"action": "get_product_info", "action_input": patterns["product_id"].group(1)}
        elif patterns["product_name"]:
            return {"action": "get_product_info", "action_input": patterns["product_name"].group(1)}
    
    return None

async def handle_warranty_safeguard(user_id: str, message: str, last_messages: list):
    """Handle warranty queries that need product context."""
    product_match = re.search(r"\bP\d+\b", message)
    
    if not re.search(r"\b(garansi|warranty)\b", message, re.I):
        return None
    
    if product_match:
        return {"action": "get_warranty_info", "action_input": product_match.group(0)}
    
    # Search for product context
    chosen_product = None
    
    # Check latest order
    async with AsyncSessionLocal() as session:
        q = await session.execute(
            sqlalchemy.select(Order)
            .where(Order.user_id == user_id)
            .order_by(Order.created_at.desc())
            .limit(1)
        )
        last_order = q.scalars().first()
        if last_order:
            chosen_product = last_order.product_id
    
    # Check chat history for product ID
    if not chosen_product:
        for m in last_messages:
            pm = re.search(r"\bP\d+\b", m["content"])
            if pm:
                chosen_product = pm.group(0)
                break
    
    if chosen_product:
        return {"action": "get_warranty_info", "action_input": chosen_product}
    
    return "ask_product"

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    user_id = req.user_id
    user_message = req.message.strip()

    # Store user message
    await persist_message(user_id, "user", user_message)

    # Fetch last 3 messages for context
    last_messages = await get_last_n_messages(user_id, n=3)

    # Ask LLM
    try:
        llm_text = llm.ask(last_messages, user_message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM error: {e}")

    action_json = try_parse_json_action(llm_text)

    # Warranty safeguard
    warranty_result = await handle_warranty_safeguard(user_id, user_message, last_messages)
    if warranty_result == "ask_product":
        reply = "Produk mana yang ingin Anda ketahui informasi garansinya?"
        await persist_message(user_id, "assistant", reply)
        return ChatResponse(reply=reply, tool_called=None, tool_output=None)
    elif warranty_result:
        action_json = warranty_result

    # Fallback when LLM doesn't provide action
    if not action_json or action_json.get("action") == "none":
        patterns = await extract_patterns(user_message)
        action_json = determine_fallback_action(user_message, patterns)

    # Execute tools
    tool_called = None
    tool_output = None
    assistant_reply = llm_text

    if action_json and action_json.get("action") and action_json.get("action") != "none":
        action = action_json.get("action")
        action_input = action_json.get("action_input", "")
        tool_called = action

        if action == "get_order_status":
            async with AsyncSessionLocal() as session:
                order_id = action_input.strip()

                if not order_id:
                    # Look for order in history or get latest
                    history_orders = [re.search(r"(ORD\d+)", m["content"]) for m in last_messages]
                    last_order_id = next((h.group(1) for h in history_orders if h), None)

                    if last_order_id:
                        tool_output = await get_user_order_status(session, user_id, last_order_id)
                    else:
                        latest_order = await get_latest_order_for_user(session, user_id)
                        if latest_order:
                            tool_output = {
                                "found": True,
                                "order_id": latest_order.order_id,
                                "status": latest_order.status,
                                "tracking": latest_order.tracking,
                                "user_id": latest_order.user_id,
                                "product_id": latest_order.product.id if latest_order.product else None,
                                "product_name": latest_order.product.name if latest_order.product else None,
                            }
                        else:
                            tool_output = {"found": False, "order_id": None}
                else:
                    tool_output = await get_user_order_status(session, user_id, order_id)

            if tool_output.get("found"):
                assistant_reply = (
                    f"Pesanan {tool_output['order_id']} saat ini berstatus: {tool_output['status']}."
                    + (f" Tracking: {tool_output['tracking']}." if tool_output.get("tracking") else "")
                )
            else:
                assistant_reply = "Anda tidak memiliki pesanan dengan nomor tersebut."

        elif action == "get_warranty_info":
            async with AsyncSessionLocal() as session:
                tool_output = await get_warranty_info(session, action_input)
            if tool_output:
                assistant_reply = (
                    "Anda dapat mengklaim garansi dengan mengirim email ke warranty@company.com. "
                    "Pastikan klaim Anda sesuai dengan detail garansi produk. "
                    "Detailnya adalah sebagai berikut.\n\n"
                    f"Produk {tool_output['product']} memiliki garansi selama "
                    f"{tool_output['duration_months']} bulan. Ketentuan: {tool_output['terms']}"
                )
            else:
                assistant_reply = f"Maaf — saya tidak dapat menemukan informasi garansi untuk produk {action_input}."

        elif action == "get_product_info":
            async with AsyncSessionLocal() as session:
                tool_output = await get_product_info(session, action_input)

            if tool_output:
                msg_lower = user_message.lower()
                if re.search(r"\b(kelebihan|keunggulan|pros|advantage)\b", msg_lower):
                    assistant_reply = f"Kelebihan {tool_output['name']}: {tool_output.get('pros','Tidak tersedia')}"
                elif re.search(r"\b(kekurangan|kelemahan|cons|disadvantage)\b", msg_lower):
                    assistant_reply = f"Kekurangan {tool_output['name']}: {tool_output.get('cons','Tidak tersedia')}"
                elif re.search(r"\b(deskripsi|description|detail|tentang|about)\b", msg_lower):
                    assistant_reply = f"Deskripsi {tool_output['name']}: {tool_output['description']}"
                else:
                    assistant_reply = (
                        f"Produk {tool_output['name']} (ID: {tool_output['id']}).\n"
                        f"Deskripsi: {tool_output['description']}\n"
                        f"Kelebihan: {tool_output.get('pros','Tidak tersedia')}\n"
                        f"Kekurangan: {tool_output.get('cons','Tidak tersedia')}"
                    )
            else:
                assistant_reply = f"Maaf — saya tidak dapat menemukan informasi produk untuk {action_input}."

        else:
            assistant_reply = f"Tool '{action}' yang diminta tidak didukung."
            tool_output = {"error": "unsupported_tool"}

        # Persist tool output
        await persist_message(user_id, "tool", json.dumps({"tool": action, "output": tool_output}))

    # Persist assistant reply
    await persist_message(user_id, "assistant", assistant_reply)

    return ChatResponse(reply=assistant_reply, tool_called=tool_called, tool_output=tool_output)

@app.delete("/database/clear")
async def clear_database():
    """Clear all data from the database (dangerous operation)."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(sqlalchemy.text("DELETE FROM messages"))
            await session.execute(sqlalchemy.text("DELETE FROM orders"))  
            await session.execute(sqlalchemy.text("DELETE FROM products"))
            await session.execute(sqlalchemy.text("DELETE FROM warranties"))
            await session.commit()
            
            global _product_patterns_cache, _cache_timestamp
            _product_patterns_cache = None
            _cache_timestamp = None
            
        return {"message": "Database cleared successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error clearing database: {e}")

@app.post("/database/seed")
async def seed_database_endpoint():
    """Seed the database with initial data."""
    try:
        await seed_database()
        
        global _product_patterns_cache, _cache_timestamp
        _product_patterns_cache = None
        _cache_timestamp = None
        
        return {"message": "Database seeded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error seeding database: {e}")

@app.post("/database/reset")
async def reset_database():
    """Clear and reseed the database (full reset)."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(sqlalchemy.text("DELETE FROM messages"))
            await session.execute(sqlalchemy.text("DELETE FROM orders"))
            await session.execute(sqlalchemy.text("DELETE FROM products"))
            await session.execute(sqlalchemy.text("DELETE FROM warranties"))
            await session.commit()
        
        await seed_database()
        
        global _product_patterns_cache, _cache_timestamp
        _product_patterns_cache = None
        _cache_timestamp = None
        
        return {"message": "Database reset successfully (cleared and reseeded)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error resetting database: {e}")

@app.get("/database/status")
async def database_status():
    """Get database status and record counts."""
    try:
        async with AsyncSessionLocal() as session:
            # Count records in each table
            message_count = await session.execute(sqlalchemy.text("SELECT COUNT(*) FROM messages"))
            order_count = await session.execute(sqlalchemy.text("SELECT COUNT(*) FROM orders"))
            product_count = await session.execute(sqlalchemy.text("SELECT COUNT(*) FROM products"))
            warranty_count = await session.execute(sqlalchemy.text("SELECT COUNT(*) FROM warranties"))
            
            return {
                "status": "connected",
                "tables": {
                    "messages": message_count.scalar(),
                    "orders": order_count.scalar(),
                    "products": product_count.scalar(),
                    "warranties": warranty_count.scalar()
                },
                "cache_status": {
                    "patterns_cached": _product_patterns_cache is not None,
                    "cache_age_seconds": int(time.time() - _cache_timestamp) if _cache_timestamp else None
                }
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error checking database status: {e}")

@app.get("/history/{user_id}")
async def history(user_id: str):
    """Get conversation history for a user."""
    return await get_all_messages_for_user(user_id)

@app.get("/order/{order_id}")
async def order_status_endpoint(order_id: str):
    """Get order status by order ID."""
    data = await get_order_status(order_id)
    if not data.get("found"):
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return data

@app.get("/users/{user_id}/orders")
async def user_orders(user_id: str):
    """Get all orders for a specific user."""
    return await get_all_orders_for_user(user_id)

@app.get("/products/{product_id}")
async def get_product_endpoint(product_id: str):
    """Get product information by product ID."""
    async with AsyncSessionLocal() as session:
        product_info = await get_product_info(session, product_id)
        if not product_info:
            raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
        return product_info

@app.get("/products")
async def list_products():
    """List all products."""
    return await get_all_products()

@app.get("/warranties")
async def list_warranties():
    """List all warranty policies."""
    return await get_all_warranties()