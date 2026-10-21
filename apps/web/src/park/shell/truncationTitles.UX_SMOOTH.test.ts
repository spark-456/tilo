// @vitest-environment happy-dom
// UX-SMOOTH: text the layout cuts short gets its whole wording as a hover title; a title the page set is kept, and a
// title this helper set goes once the text fits.
import { afterEach, expect, it } from "vitest";
import { titleCutText } from "./truncationTitles";

afterEach(() => {
  document.body.innerHTML = "";
});

function cut(text: string, fits: boolean, title?: string): HTMLElement {
  const el = document.createElement("span");
  el.textContent = text;
  el.style.textOverflow = "ellipsis";
  el.style.overflow = "hidden";
  if (title) el.title = title;
  Object.defineProperty(el, "clientWidth", { configurable: true, get: () => 100 });
  Object.defineProperty(el, "scrollWidth", { configurable: true, get: () => (fits ? 100 : 240) });
  document.body.append(el);
  return el;
}

it("UX_SMOOTH_cut_text_gets_its_whole_wording_as_a_title", () => {
  const el = cut("Open wikipedia.org and summarise the history section", false);
  titleCutText(el);
  expect(el.title).toBe("Open wikipedia.org and summarise the history section");
});

it("UX_SMOOTH_text_that_fits_gets_no_title_and_a_page_title_is_kept", () => {
  const fits = cut("Short", true);
  titleCutText(fits);
  expect(fits.hasAttribute("title")).toBe(false);
  const own = cut("Long name", false, "The page's own words");
  titleCutText(own);
  expect(own.title).toBe("The page's own words");
});

it("UX_SMOOTH_a_title_it_set_goes_once_the_text_fits", () => {
  const el = cut("A long run name", false);
  titleCutText(el);
  expect(el.title).toBe("A long run name");
  Object.defineProperty(el, "scrollWidth", { configurable: true, get: () => 100 });
  titleCutText(el);
  expect(el.hasAttribute("title")).toBe(false);
});
