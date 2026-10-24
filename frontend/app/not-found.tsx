import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto mt-16 max-w-md text-center">
      <p className="eyebrow">404</p>
      <h1 className="mt-1 text-xl font-semibold">No such page</h1>
      <Link href="/" className="mt-4 inline-block text-accent hover:underline">
        Back to the dashboard
      </Link>
    </div>
  );
}
