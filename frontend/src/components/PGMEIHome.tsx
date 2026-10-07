export default function PGMEIHome() {
  return (
    <iframe
      src="/pgmei.html"
      title="PGMEI - Programa Gerador de DAS do Microempreendedor Individual"
      data-testid="pgmei-frame"
      style={{
        position: "fixed",
        top: 0,
        left: 0,
        width: "100%",
        height: "100%",
        border: "none",
      }}
    />
  );
}
