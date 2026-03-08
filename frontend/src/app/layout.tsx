import type { Metadata } from "next";
import { Sora, DM_Sans, DM_Mono, Instrument_Serif } from "next/font/google";
import "./globals.css";

const sora = Sora({ subsets: ["latin"], variable: "--font-sora" });
const dmSans = DM_Sans({ subsets: ["latin"], variable: "--font-dm-sans" });
const dmMono = DM_Mono({ subsets: ["latin"], weight: "400", variable: "--font-dm-mono" });
const instrumentSerif = Instrument_Serif({ subsets: ["latin"], weight: "400", style: ["normal", "italic"], variable: "--font-serif" });

export const metadata: Metadata = {
  title: "Carvex",
  description: "Your car agent. Finds it. Scores it. Negotiates it.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${dmSans.className} ${sora.variable} ${dmSans.variable} ${dmMono.variable} ${instrumentSerif.variable} antialiased`}>
        {children}
      </body>
    </html>
  );
}
