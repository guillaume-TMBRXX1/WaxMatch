import Link from "next/link";
import { Logo, Wordmark } from "./Logo";
import { DesktopNav } from "./Nav";
import { ThemeToggle } from "./ThemeToggle";

export function Header() {
  return (
    <header className="header">
      <Link href="/" className="brand" aria-label="WaxMatch, accueil">
        <Logo />
        <Wordmark />
      </Link>
      <DesktopNav />
      <ThemeToggle />
    </header>
  );
}
