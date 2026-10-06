// SEC-15: what a visitor sees. No form, no upload, no way into the product: the server refuses every call.
export function UnderConstruction() {
  return (
    <div className="screen-body" data-testid="under-construction">
      <h1>Tilo is still under construction</h1>
      <p>
        Tilo is still under construction and not open to the public yet. Please check back later.
      </p>
    </div>
  );
}
