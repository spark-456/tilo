try {
  if (sessionStorage.getItem("tilo-boot-seen") === "1")
    document.documentElement.classList.add("tilo-returning-session");
} catch {}
