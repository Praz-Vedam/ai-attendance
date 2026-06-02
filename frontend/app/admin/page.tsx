"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import {
  attendanceSnapshotUrl,
  getAttendanceStatus,
  listStudents,
  startAttendance,
  stopAttendance,
  type AttendanceStatus,
  type StudentProfile,
} from "@/lib/api";

export default function AdminPage() {
  const [status, setStatus] = useState<AttendanceStatus | null>(null);
  const [students, setStudents] = useState<StudentProfile[]>([]);
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [polling, setPolling] = useState(true);
  const [selectedClassroom, setSelectedClassroom] = useState("Classroom 1");

  const refreshStatus = useCallback(async () => {
    try {
      const [attendance, roster] = await Promise.all([
        getAttendanceStatus(),
        listStudents(),
      ]);
      setStatus(attendance);
      setStudents(roster);
      setMessage("");
    } catch {
      setMessage("Could not reach the attendance API. Is the backend running?");
    }
  }, []);

  useEffect(() => {
    refreshStatus();
  }, [refreshStatus]);

  useEffect(() => {
    if (!polling) return;

    const interval = setInterval(refreshStatus, 4000);
    return () => clearInterval(interval);
  }, [polling, refreshStatus]);

  const handleStart = async () => {
    setLoading(true);
    setMessage("");

    try {
      const data = await startAttendance(selectedClassroom);
      setMessage(data.message);
      await refreshStatus();
    } catch {
      setMessage("Failed to start attendance session");
    }

    setLoading(false);
  };

  const handleStop = async () => {
    setLoading(true);
    setMessage("");

    try {
      const data = await stopAttendance();
      setMessage(
        `${data.message}${data.marked_count !== undefined ? ` — ${data.marked_count} student(s) marked` : ""}`
      );
      await refreshStatus();
    } catch {
      setMessage("Failed to stop attendance session");
    }

    setLoading(false);
  };

  const sessionActive = status?.active ?? false;
  const successMessage =
    message.includes("started") ||
    message.includes("stopped") ||
    message.includes("marked");

  const markedByEmail = new Map(
    status?.marked_students.map((student) => [student.email, student]) ?? []
  );

  return (
    <main className="min-h-screen bg-black text-white px-6 py-10">
      <div className="max-w-5xl mx-auto space-y-8">
        <div>
          <Link
            href="/"
            className="text-zinc-400 hover:text-white text-sm mb-4 inline-block"
          >
            ← Home
          </Link>
          <h1 className="text-4xl font-bold mb-2">Teacher / Admin</h1>
          <p className="text-zinc-400">
            Start or stop the attendance window and view enrolled students by
            name and face registration status.
          </p>
        </div>

        <div className="bg-zinc-900 border border-zinc-800 rounded-3xl p-8 space-y-6">
          <div className="flex items-center justify-between gap-4 flex-wrap">
            <div>
              <h2 className="text-2xl font-semibold mb-1">Session status</h2>
              <p
                className={`text-lg font-medium ${
                  sessionActive ? "text-green-400" : "text-zinc-400"
                }`}
              >
                {sessionActive ? "Attendance open" : "Attendance closed"}
              </p>
              {status?.started_at && sessionActive && (
                <p className="text-sm text-zinc-500 mt-1">
                  Started {new Date(status.started_at).toLocaleString()}
                </p>
              )}
              {status?.teacher_ip && (
                <p className="text-sm text-zinc-400 mt-1 font-mono">
                  Teacher IP: {status.teacher_ip}
                </p>
              )}
            </div>

            <label className="flex items-center gap-2 text-sm text-zinc-400">
              <input
                type="checkbox"
                checked={polling}
                onChange={(e) => setPolling(e.target.checked)}
                className="rounded"
              />
              Auto-refresh
            </label>
          </div>

          <div className="flex flex-wrap gap-4 items-end">
            <div>
              <label className="block text-sm font-medium text-zinc-400 mb-2">
                Select Classroom
              </label>
              <select
                value={selectedClassroom}
                onChange={(e) => setSelectedClassroom(e.target.value)}
                disabled={sessionActive || loading}
                className="bg-zinc-800 border border-zinc-700 rounded-lg px-4 py-2 text-white disabled:opacity-40"
              >
                <option>Classroom 1</option>
                <option>Classroom 2</option>
                <option>Classroom 3</option>
              </select>
            </div>

            <button
              type="button"
              onClick={handleStart}
              disabled={loading || sessionActive}
              className="bg-green-600 hover:bg-green-500 disabled:opacity-40 disabled:cursor-not-allowed transition px-8 py-4 rounded-2xl font-semibold text-lg"
            >
              Start attendance
            </button>

            <button
              type="button"
              onClick={handleStop}
              disabled={loading || !sessionActive}
              className="bg-red-600 hover:bg-red-500 disabled:opacity-40 disabled:cursor-not-allowed transition px-8 py-4 rounded-2xl font-semibold text-lg"
            >
              Stop attendance
            </button>

            <button
              type="button"
              onClick={refreshStatus}
              disabled={loading}
              className="bg-zinc-700 hover:bg-zinc-600 transition px-6 py-4 rounded-2xl font-semibold"
            >
              Refresh
            </button>
          </div>

          {status && (
            <div className="pt-4 border-t border-zinc-800">
              <h3 className="text-lg font-semibold mb-3">
                Marked this session ({status.marked_count})
              </h3>
              {status.marked_students.length === 0 ? (
                <p className="text-zinc-500">No students have marked yet.</p>
              ) : (
                <ul className="space-y-3">
                  {status.marked_students.map((student) => (
                    <li
                      key={student.email}
                      className="bg-zinc-800 px-4 py-3 rounded-xl text-sm flex flex-wrap items-start gap-x-4 gap-y-2"
                    >
                      {student.has_snapshot && (
                        <img
                          src={attendanceSnapshotUrl(student.email)}
                          alt={`${student.name} at mark attendance`}
                          className="w-24 h-24 rounded-xl object-cover border border-zinc-600 shrink-0"
                        />
                      )}
                      <span className="font-medium text-white">
                        {student.name}
                      </span>
                      <span className="text-zinc-500">
                        {new Date(student.marked_at).toLocaleString()}
                      </span>
                      {status.teacher_ip && (
                        <span
                          className={`font-mono text-xs ${
                            student.ip_match === false
                              ? "text-red-400"
                              : "text-zinc-400"
                          }`}
                        >
                          Teacher IP: {status.teacher_ip}
                        </span>
                      )}
                      {student.student_ip && (
                        <span
                          className={`font-mono text-xs ${
                            student.ip_match === false
                              ? "text-red-400"
                              : "text-zinc-400"
                          }`}
                        >
                          Student IP: {student.student_ip}
                        </span>
                      )}
                      {student.location && (
                        <span className="text-zinc-400">
                          Location: <span className="text-white font-medium">{student.location}</span>
                        </span>
                      )}
                      {student.location_confidence !== undefined && (
                        <span className="text-zinc-400">
                          Confidence: <span className="text-white font-medium">
                            {(student.location_confidence * 100).toFixed(2)}%
                          </span>
                        </span>
                      )}
                      {student.status && (
                        <span className={`px-3 py-1 rounded-full text-xs font-semibold ${
                          student.status === "Present"
                            ? "bg-green-900/30 text-green-400"
                            : "bg-red-900/30 text-red-400"
                        }`}>
                          {student.status}
                        </span>
                      )}
                      {student.reason && (
                        <span className="text-red-400 text-xs">
                          Reason: {student.reason}
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>

        <div className="bg-zinc-900 border border-zinc-800 rounded-3xl p-8 space-y-4 overflow-x-auto">
          <h2 className="text-2xl font-semibold">Student roster</h2>
          <p className="text-zinc-400 text-sm">
            Each student is identified by the name and face scans from signup.
          </p>

          {students.length === 0 ? (
            <p className="text-zinc-500">No student accounts yet.</p>
          ) : (
            <table className="w-full text-left text-sm min-w-[760px]">
              <thead>
                <tr className="text-zinc-400 border-b border-zinc-800">
                  <th className="py-3 pr-4 font-medium">Name</th>
                  <th className="py-3 pr-4 font-medium">Face</th>
                  <th className="py-3 pr-4 font-medium">Registered at</th>
                  <th className="py-3 pr-4 font-medium">Snapshot</th>
                  <th className="py-3 pr-4 font-medium">This session</th>
                  <th className="py-3 pr-4 font-medium">Expected</th>
                  <th className="py-3 pr-4 font-medium">Detected</th>
                  <th className="py-3 pr-4 font-medium">Confidence</th>
                  <th className="py-3 pr-4 font-medium">Status</th>
                  <th className="py-3 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {students.map((student) => {
                  const marked = markedByEmail.get(student.email);
                  return (
                  <tr
                    key={student.email}
                    className="border-b border-zinc-800/80 last:border-0"
                  >
                    <td className="py-3 pr-4 text-white">{student.name}</td>
                    <td className="py-3 pr-4">
                      <span
                        className={
                          student.face_registered
                            ? "text-green-400"
                            : "text-amber-400"
                        }
                      >
                        {student.face_registered
                          ? `Linked to ${student.name}`
                          : "Pending"}
                      </span>
                    </td>
                    <td className="py-3 pr-4 text-zinc-500">
                      {student.face_registered_at
                        ? new Date(
                            student.face_registered_at
                          ).toLocaleString()
                        : "—"}
                    </td>
                    <td className="py-3 pr-4">
                      {marked?.has_snapshot ? (
                        <img
                          src={attendanceSnapshotUrl(student.email)}
                          alt={`${student.name} webcam at mark attendance`}
                          className="w-16 h-16 rounded-lg object-cover border border-zinc-600"
                        />
                      ) : marked ? (
                        <span className="text-zinc-500 text-xs">—</span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="py-3 pr-4">
                      {marked ? (
                        <span className="text-green-400">Present</span>
                      ) : sessionActive ? (
                        <span className="text-zinc-500">Not yet</span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="py-3 pr-4">
                      {status?.expected_classroom ? (
                        <span className="text-white">{status.expected_classroom}</span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="py-3 pr-4">
                      {marked?.location ? (
                        <span className="text-white">{marked.location}</span>
                      ) : marked ? (
                        <span className="text-zinc-500">—</span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="py-3 pr-4">
                      {marked?.location_confidence !== undefined ? (
                        <span className="text-white font-mono text-xs">
                          {(marked.location_confidence * 100).toFixed(2)}%
                        </span>
                      ) : marked ? (
                        <span className="text-zinc-500">—</span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="py-3 pr-4">
                      {marked?.status ? (
                        <span className={`px-2 py-1 rounded text-xs font-semibold ${
                          marked.status === "Present"
                            ? "bg-green-900/30 text-green-400"
                            : "bg-red-900/30 text-red-400"
                        }`}>
                          {marked.status}
                        </span>
                      ) : marked ? (
                        <span className="text-zinc-500">—</span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                    <td className="py-3">
                      {marked?.reason ? (
                        <span className="text-red-400 text-xs">{marked.reason}</span>
                      ) : marked ? (
                        <span className="text-zinc-500">—</span>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <p className="text-zinc-500 text-sm">
          Students sign up at{" "}
          <Link
            href="/register-student"
            className="text-blue-400 hover:text-blue-300"
          >
            /register-student
          </Link>{" "}
          (name + face scans), then sign in at{" "}
          <Link href="/login" className="text-blue-400 hover:text-blue-300">
            /login
          </Link>{" "}
          to mark attendance.
        </p>

        {message && (
          <div
            className={`w-fit px-8 py-5 rounded-2xl text-lg font-semibold border ${
              successMessage
                ? "bg-green-600/20 text-green-400 border-green-500"
                : "bg-red-600/20 text-red-400 border-red-500"
            }`}
          >
            {message}
          </div>
        )}
      </div>
    </main>
  );
}
