import "./thinkingTilo.css";

const MOTION = "/loader/thinking-e4ab588622e7.webp";
const STILL = "/loader/thinking-3c45b79799e6.png";

/** A saved Tilo T thinking loop, shown only while the caller has a real pending action. */
export function ThinkingTilo({
  label = "Tilo is thinking",
  size = 24,
  still = false,
  decorative = false,
}: {
  label?: string;
  size?: 20 | 24 | 32;
  still?: boolean;
  decorative?: boolean;
}) {
  return (
    <span
      className={`thinking-tilo${still ? " thinking-tilo--still" : ""}`}
      role={decorative ? undefined : "status"}
      aria-label={decorative ? undefined : label}
      aria-hidden={decorative ? true : undefined}
      style={{ width: size, height: Math.round((size * 58) / 48) }}
    >
      <picture>
        <source media="(prefers-reduced-motion: reduce)" srcSet={STILL} />
        <img src={MOTION} alt="" width="96" height="116" />
      </picture>
      <img className="thinking-tilo__still" src={STILL} alt="" width="96" height="116" />
    </span>
  );
}
