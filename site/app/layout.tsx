import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: { default: "Build your own AI SRE · MongoDB Dublin", template: "%s · MongoDB Dublin lab" },
  description:
    "The guided build from Bronto and MongoDB's AI Observability & Monitoring evening in Dublin: trace an AI agent, connect app traces with MongoDB Atlas metrics, and find a production incident's root cause.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        {/* eslint-disable-next-line @next/next/no-page-custom-font */}
        <link
          href="https://fonts.googleapis.com/css2?family=Geist+Mono:wght@400;600&family=Radio+Canada+Big:wght@400;600;700&family=Source+Serif+4:wght@500;600&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <header className="site-header">
          <Link href="/" className="brand">
            <img src="/img/bronto-dino.png" alt="" width={28} height={28} />
            <span>MongoDB Dublin lab</span>
          </Link>
          <nav aria-label="Main">
            <a href="https://ai-observability-dublin.vercel.app" target="_blank" rel="noopener">Slides</a>
          </nav>
        </header>
        <main>{children}</main>
        <footer className="site-footer">
          <span>
            From Bronto &times; MongoDB, &ldquo;AI Observability &amp; Monitoring&rdquo;, Dublin AI Week.
          </span>
          <span>
            <a href="https://github.com/bronto-community/mongodb-dublin-lab" target="_blank" rel="noopener">Source on GitHub</a>
            {" · "}
            <a href="https://bronto.io" target="_blank" rel="noopener">bronto.io</a>
          </span>
        </footer>
      </body>
    </html>
  );
}
