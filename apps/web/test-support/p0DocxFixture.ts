// A tiny recorded DOCX-shaped ZIP with a heading, emphasized phrase, and two-row table.
const BASE64 =
  "UEsDBBQAAAAIAHy5U11gyndO4QAAADACAAARAAAAd29yZC9kb2N1bWVudC54bWyVkk1uwyAQha+CfIBM2kWlIodFkkV3rdQTYCCxJWAQTEt9+9r4p2rrqOpmRqP53nsgqDPXqN6c8cQ+nPWJ50PVEgUOkFRrnEw7DMYPuwtGJ2kY4xUyRh0iKpNS56/Owv1+/wBOdr4SdeYN6n7soZSXWNor9dawzN+lPVRPRupBeVeBqGFlSiFxNqpLHXrWxM5cxj0VKk7s6jzjpxYxGfaNW8rk20wp80QCA432xy0JCUaoZb/bzKXGljah6udRnovxhhIW+rfmhIluK2ANuxF5/F/a459RMN8SlneErz8iPgFQSwECFAAUAAAACAB8uVNdYMp3TuEAAAAwAgAAEQAAAAAAAAAAAAAAgAEAAAAAd29yZC9kb2N1bWVudC54bWxQSwUGAAAAAAEAAQA/AAAAEAEAAAAA";

export function p0DocxBlob(): Blob {
  const bytes = Uint8Array.from(atob(BASE64), (char) => char.charCodeAt(0));
  return new Blob([bytes.buffer], {
    type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  });
}
