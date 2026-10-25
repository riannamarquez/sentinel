import type { Metadata } from "next";
import { Newsreader } from "next/font/google";
import "./globals.css";

// The one typeface; the theme in globals.css reads it through --font-newsreader.
const newsreader = Newsreader({
  variable: "--font-newsreader",
  subsets: ["latin"],
  axes: ["opsz"],
});

export const metadata: Metadata = {
  title: "Sentinel · Rule change review",
  description: "Red finds a gap, Blue proposes a rule, deterministic code scores it, and a human decides.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${newsreader.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
