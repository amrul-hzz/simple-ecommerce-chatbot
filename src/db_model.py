from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from dotenv import load_dotenv
import os
import datetime

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

engine = create_async_engine(DATABASE_URL, echo=False, future=True)
AsyncSessionLocal = sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

Base = declarative_base()

class Message(Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String, index=True)
    role = Column(String)
    content = Column(Text)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class Warranty(Base):
    __tablename__ = "warranties"
    id = Column(Integer, primary_key=True, index=True)
    duration_months = Column(Integer, nullable=False)
    terms = Column(Text, nullable=False)

class Product(Base):
    __tablename__ = "products"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    pros = Column(Text)
    cons = Column(Text)
    warranty_id = Column(Integer, ForeignKey("warranties.id"))

    warranty = relationship("Warranty", backref="products")

class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(String, unique=True, index=True)
    user_id = Column(String, index=True)
    status = Column(String)
    tracking = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    product = relationship("Product", backref="orders")