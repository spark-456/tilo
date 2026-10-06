// THROWAWAY (WEB-3b validation only).
export function BootSplash({ ready }: { ready: boolean }) {
  if (ready) return null;
  return (
    <div className="park-boot" role="status" aria-label="Loading Tilo">
      <div className="park-boot__logo">
        <div className="park-boot__tile">
          <div className="park-boot__visor">
            <span className="park-boot__eye" />
            <span className="park-boot__eye" />
          </div>
        </div>
        <div className="park-boot__word">tilo</div>
      </div>
      <div className="park-boot__bottom">
        <div className="park-boot__track">
          <div className="park-boot__fill" />
        </div>
        <div className="park-boot__label">Loading your city</div>
      </div>
    </div>
  );
}
