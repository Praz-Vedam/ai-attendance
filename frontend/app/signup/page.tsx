"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

export default function SignupRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    router.replace("/register-student");
  }, [router]);

  return (
    <main className="min-h-screen bg-black text-white px-6 py-10">
      <p className="text-zinc-400">Redirecting to register student…</p>
    </main>
  );
}
