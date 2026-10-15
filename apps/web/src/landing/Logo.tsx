// STUDIO-6: the Studio logo of the signed-out pages ("Tilo S Landing" header): the filled mark with its visor and the
// word "tilo". One accessible name ("tilo"); the drawing is decoration. Styled by landing.css, colours are tokens.
export function Logo({ href }: { readonly href?: string }) {
  const body = (
    <>
      <span className="landing-logo__mark" aria-hidden="true">
        <span className="landing-logo__visor">
          <span />
          <span />
        </span>
      </span>
      <span className="landing-logo__word" aria-hidden="true">
        tilo
      </span>
    </>
  );
  return href ? (
    <a className="landing-logo" href={href} aria-label="tilo, home">
      {body}
    </a>
  ) : (
    <span className="landing-logo" role="img" aria-label="tilo">
      {body}
    </span>
  );
}
