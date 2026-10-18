document.addEventListener(
  "submit",
  (event) => {
    if (!(event.target instanceof HTMLFormElement)) return;
    event.preventDefault();
    const fields = Object.create(null);
    new FormData(event.target).forEach((value, key) => {
      if (typeof value === "string" && key !== "__proto__") fields[key] = value;
    });
    window.parent.postMessage({ type: "tilo-form-submit", fields: fields }, "*");
  },
  true,
);
