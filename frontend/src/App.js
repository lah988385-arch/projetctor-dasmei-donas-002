import { BrowserRouter, Routes, Route } from "react-router-dom";
import PGMEIHome from "@/components/PGMEIHome";
import AdminApp from "@/admin/AdminApp";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<PGMEIHome />} />
          <Route path="/donaspainel/*" element={<AdminApp />} />
        </Routes>
      </BrowserRouter>
    </div>
  );
}

export default App;
