import Script from "next/script";

/**
 * Static shell — no client component, no hydration, so it ships from the CDN and
 * paints immediately. The thread is deliberately an empty container that
 * public/chat.js owns and mutates directly; React never re-renders this page, so
 * there is nothing for the two to fight over.
 */
export default function Page() {
  return (
    <>
      <div className="topbar">
        <span className="spacer" />
        <button className="reset" id="reset" type="button">
          <svg viewBox="0 0 24 24">
            <path d="M15.5 4.5a2.12 2.12 0 0 1 3 3L8 18l-4 1 1-4Z" />
            <path d="M13.5 6.5l3 3" />
          </svg>
          <span>New chat</span>
        </button>
      </div>

      <main>
        <div className="thread" id="thread" />
      </main>

      <footer>
        <form className="composer" id="composer">
          <textarea id="input" rows={1} placeholder="Ask about a refund..." autoFocus />
          <button className="send" id="send" type="submit" aria-label="Send" disabled>
            <svg viewBox="0 0 24 24">
              <path d="M12 19V5M6 11l6-6 6 6" />
            </svg>
          </button>
        </form>
      </footer>

      <div className="modal" id="modal" hidden>
        <div className="modal-card">
          <div className="modal-head">
            <span id="modalIcon" />
            <span className="mt" id="modalTitle" />
            <span className="spacer" />
            <button className="modal-close" type="button" aria-label="Close">
              &times;
            </button>
          </div>
          <div className="modal-body" id="modalBody" />
        </div>
      </div>

      <Script src="/chat.js" strategy="afterInteractive" />
    </>
  );
}
