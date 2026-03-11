import { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import axios from 'axios'
import { UploadCloud, FileSpreadsheet, CheckCircle2, AlertCircle, Database, LayoutDashboard, Package, Trash2, Loader2 } from 'lucide-react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE 

function Navigation() {
  const location = useLocation();
  return (
    <header>
      <div className="logo">
        <Database className="upload-icon" style={{width: 32, height: 32, marginBottom: 0}} />
        ETL AI Prototype
      </div>
      <nav>
        <Link to="/" className={`nav-link ${location.pathname === '/' ? 'active' : ''}`}>
          <UploadCloud size={20} style={{display: 'inline', marginRight: 8, verticalAlign: 'text-bottom'}} />
          Upload Data
        </Link>
        <Link to="/products" className={`nav-link ${location.pathname === '/products' ? 'active' : ''}`}>
          <LayoutDashboard size={20} style={{display: 'inline', marginRight: 8, verticalAlign: 'text-bottom'}} />
          Products Database
        </Link>
      </nav>
    </header>
  )
}

function UploadPage() {
  const [file, setFile] = useState(null)
  const [dragActive, setDragActive] = useState(false)
  const [loading, setLoading] = useState(false)
  const [toast, setToast] = useState(null)

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === "dragenter" || e.type === "dragover") {
      setDragActive(true);
    } else if (e.type === "dragleave") {
      setDragActive(false);
    }
  };

  const handleDrop = (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
      setFile(e.dataTransfer.files[0]);
    }
  };

  const handleChange = (e) => {
    e.preventDefault();
    if (e.target.files && e.target.files[0]) {
      setFile(e.target.files[0]);
    }
  };

  const showToast = (message, type = 'success') => {
    setToast({ message, type })
    setTimeout(() => setToast(null), 3000)
  }

  const handleUpload = async () => {
    if (!file) return;
    setLoading(true);

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await axios.post(`${API_BASE}/upload/`, formData, {
        headers: { 'Content-Type': 'multipart/form-data' }
      });
      showToast(`Successfully extracted ${res.data.data.length} products!`);
      setFile(null);
    } catch (err) {
      showToast(err.response?.data?.error || 'Failed to process file', 'error');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page fade-in">
      <div>
        <h1>Upload Unstructured Data</h1>
        <p className="upload-hint" style={{marginBottom: 0}}>
          Upload raw CSV, Excel, or JSON files. Our Gemini LLM will intelligently parse and map unstructured data to specific fields like price, category, etc.
        </p>
      </div>

      <div 
        className={`upload-area ${dragActive ? 'drag-active' : ''}`}
        onDragEnter={handleDrag}
        onDragLeave={handleDrag}
        onDragOver={handleDrag}
        onDrop={handleDrop}
      >
        <UploadCloud className="upload-icon" />
        <div className="upload-text">Drag and drop your file here</div>
        <div className="upload-hint">or click to browse your computer (CSV, XLSX, JSON)</div>
        
        <label className="label-btn">
          Select File
          <input type="file" onChange={handleChange} title="Upload CSV, Excel, or JSON" />
        </label>
      </div>

      {file && (
        <div className="file-info">
          <div style={{display: 'flex', alignItems: 'center', gap: '1rem'}}>
            <FileSpreadsheet color="#4f46e5" size={32} />
            <div>
              <div style={{fontWeight: 600}}>{file.name}</div>
              <div style={{fontSize: '0.875rem', color: 'var(--text-muted)'}}>
                {(file.size / 1024).toFixed(2)} KB
              </div>
            </div>
          </div>
          
          <div style={{display: 'flex', gap: '1rem'}}>
            <button 
              onClick={() => setFile(null)} 
              style={{background: 'rgba(239, 68, 68, 0.1)', color: '#ef4444'}}
              disabled={loading}
            >
              <Trash2 size={18} />
            </button>
            <button onClick={handleUpload} disabled={loading}>
              {loading ? <Loader2 className="loader" size={20} /> : <CheckCircle2 size={20} />}
              {loading ? 'AI Parsing...' : 'Run LLM Pipeline'}
            </button>
          </div>
        </div>
      )}

      {toast && (
        <div className={`toast ${toast.type}`}>
          {toast.type === 'error' ? <AlertCircle size={20} style={{display: 'inline', marginRight: 8, verticalAlign: 'text-bottom'}}/> : <CheckCircle2 size={20} style={{display: 'inline', marginRight: 8, verticalAlign: 'text-bottom'}}/>}
          {toast.message}
        </div>
      )}
    </div>
  )
}

function ProductsPage() {
  const [products, setProducts] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchProducts()
  }, [])

  const fetchProducts = async () => {
    try {
      const res = await axios.get(`${API_BASE}/products/`)
      setProducts(res.data)
    } catch (err) {
      console.error(err)
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (id) => {
    if (!window.confirm("Are you sure you want to delete this product?")) return;
    try {
      await axios.delete(`${API_BASE}/products/${id}/`);
      setProducts(products.filter(p => p.id !== id));
    } catch (err) {
      console.error(err);
    }
  }

  if (loading) {
    return <div style={{textAlign: 'center', padding: '4rem'}}><Loader2 className="loader upload-icon" /></div>
  }

  return (
    <div className="page fade-in">
      <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end'}}>
        <div>
          <h1>Mapped Products Database</h1>
          <p className="upload-hint">Data intelligently extracted and structured from your uploads.</p>
        </div>
        <div style={{color: 'var(--text-muted)', fontWeight: 500}}>
          Total Records: <span style={{color: 'var(--text)'}}>{products.length}</span>
        </div>
      </div>

      {products.length === 0 ? (
        <div className="card" style={{textAlign: 'center', padding: '4rem 2rem'}}>
          <Package size={48} color="var(--text-muted)" style={{marginBottom: '1rem'}} />
          <h3>No products in database</h3>
          <p className="upload-hint" style={{marginBottom: '2rem'}}>Upload an unstructured file to populate the database with AI.</p>
          <Link to="/">
             <button>Go to Upload</button>
          </Link>
        </div>
      ) : (
        <div className="table-container">
          <table>
            <thead>
              <tr>
                <th>Product Name</th>
                <th>Description</th>
                <th>Category</th>
                <th>Unit</th>
                <th>Price</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {products.map(product => (
                <tr key={product.id}>
                  <td style={{fontWeight: 500}}>{product.name}</td>
                  <td>
                    <div className="desc" title={product.description}>
                      {product.description || '-'}
                    </div>
                  </td>
                  <td>
                    <span className="category-badge">{product.category}</span>
                  </td>
                  <td style={{color: 'var(--text-muted)'}}>{product.unit_of_measurement}</td>
                  <td className="price">₹{product.price}</td>
                  <td>
                    <button 
                      onClick={() => handleDelete(product.id)}
                      style={{background: 'transparent', padding: '0.25rem', color: '#ef4444', border: '1px solid rgba(239, 68, 68, 0.2)'}}
                      title="Delete Product"
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function App() {
  return (
    <BrowserRouter>
      <div className="app-container">
        <Navigation />
        <main>
          <Routes>
            <Route path="/" element={<UploadPage />} />
            <Route path="/products" element={<ProductsPage />} />
          </Routes>
        </main>
      </div>
    </BrowserRouter>
  )
}

export default App
