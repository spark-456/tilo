// @vitest-environment happy-dom
// SIGNIN-PARK: the sign-in screen matches the user's target (a glass card over the Park city): the copy, the two
// real buttons, the legal links and the theme toggle. Tilo never handles passwords: no field and no form (PRD 16.1).
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, click, mount, q, qa } from "../../test-support/park/componentsHarness";
import { SignInScreen } from "./SignInScreen";

afterEach(cleanup);

const screen = (over: Partial<Parameters<typeof SignInScreen>[0]> = {}) => {
  const onGoogle = vi.fn();
  const onDemo = vi.fn();
  mount(
    <SignInScreen
      busy={false}
      failed={false}
      failedText="Failed."
      onGoogle={onGoogle}
      onDemo={onDemo}
      {...over}
    />,
  );
  return { onGoogle, onDemo };
};
const text = () => document.body.textContent ?? "";
const button = (re: RegExp) =>
  qa<HTMLButtonElement>(document.body, "button").find((b) =>
    re.test(`${b.textContent ?? ""} ${b.getAttribute("aria-label") ?? ""}`),
  );

describe("SIGNIN-PARK the sign-in screen", () => {
  it("SIGNIN-PARK shows the heading, the lead, the demo line and the legal line from the design", () => {
    screen();
    expect(q(document.body, "h1")?.textContent).toBe("Sign in to your city");
    expect(text()).toContain(
      "Your agents keep working while you’re away. Sign in to see what needs you.",
    );
    expect(text()).toContain("A sample company with live agents. Nothing you do is saved.");
    expect(text()).toContain("OR");
  });

  it("SIGNIN-PARK Continue with Google and Explore a demo session are real buttons that start their sign-in once", () => {
    const { onGoogle, onDemo } = screen();
    click(button(/continue with google/i) as HTMLElement);
    expect(onGoogle).toHaveBeenCalledTimes(1);
    click(button(/explore a demo session/i) as HTMLElement);
    expect(onDemo).toHaveBeenCalledTimes(1);
  });

  it("SIGNIN-PARK both buttons wait while a sign-in is running", () => {
    screen({ busy: true });
    expect((button(/continue with google/i) as HTMLButtonElement).disabled).toBe(true);
    expect((button(/explore a demo session/i) as HTMLButtonElement).disabled).toBe(true);
  });

  it("SIGNIN-PARK has no field and no form, and links Terms and Privacy Policy", () => {
    screen();
    expect(qa(document.body, "input, textarea, form")).toHaveLength(0);
    const hrefs = qa<HTMLAnchorElement>(document.body, "a").map((a) => [
      a.textContent,
      a.getAttribute("href"),
    ]);
    expect(hrefs).toEqual([
      ["Terms", "/terms"],
      ["Privacy Policy", "/privacy"],
    ]);
  });

  it("SIGNIN-PARK a failed sign-in says so in an alert", () => {
    screen({ failed: true, failedText: "Signing in did not work. Please try again." });
    expect(q(document.body, '[role="alert"]')?.textContent).toBe(
      "Signing in did not work. Please try again.",
    );
  });

  it("SIGNIN-PARK the theme toggle switches between the day and the night city", () => {
    screen();
    const root = q(document.body, '[data-testid="sign-in"]') as HTMLElement;
    expect(root.dataset.time).toBe("day");
    click(button(/night city/i) as HTMLElement);
    expect(root.dataset.time).toBe("night");
    click(button(/day city/i) as HTMLElement);
    expect(root.dataset.time).toBe("day");
  });
});
