// Fictional 10-question GATE-style practice quiz fixture for LW-14 (ADR-0029 decision 9, appspec 1.0.0).
// Every question cites a stored artifact version in the world and carries a topic slug. Server-side manifest
// publisher hosts are paired in QUIZ_FIXTURE_PUBLISHERS (AS-03: publisher comes from the manifest, never the spec).
import type { AppSpec } from "@tilo/contracts";

export const QUIZ_FIXTURE_PUBLISHERS: Readonly<Record<string, string>> = {
  art_gate_dl_paper: "gate.iitk.example.edu",
  art_gate_ds_notes: "nptel.ac.example.in",
  art_gate_algo_bank: "archive.cs.example.org",
};

export const QUIZ_FIXTURE_SPEC: AppSpec = {
  v: "1.0",
  kind: "quiz",
  title: "Computer Science Practice Set",
  theme: "metropolis",
  timer: {
    seconds: 1800,
  },
  questions: [
    {
      id: "q1",
      stem: "How many rows appear in the truth table of a 4-variable Boolean function?",
      options: {
        a: "8",
        b: "12",
        c: "16",
        d: "32",
      },
      answer: "c",
      topic: "digital_logic",
      source: {
        artifact: { artifact_id: "art_gate_dl_paper", version: 1 },
        page: 2,
      },
    },
    {
      id: "q2",
      stem: "Which two-input logic gate is functionally complete on its own?",
      options: {
        a: "XOR",
        b: "NAND",
        c: "AND",
        d: "OR",
      },
      answer: "b",
      topic: "digital_logic",
      source: {
        artifact: { artifact_id: "art_gate_dl_paper", version: 1 },
        page: 4,
      },
    },
    {
      id: "q3",
      stem: "What is the minimum number of flip-flops required to build a modulo-10 counter?",
      options: {
        a: "3",
        b: "4",
        c: "5",
        d: "10",
      },
      answer: "b",
      topic: "digital_logic",
      source: {
        artifact: { artifact_id: "art_gate_dl_paper", version: 1 },
        page: 7,
      },
    },
    {
      id: "q4",
      stem: "In a 2's complement 8-bit representation, what is the decimal range of representable integers?",
      options: {
        a: "-127 to +127",
        b: "-128 to +127",
        c: "-128 to +128",
        d: "-255 to +255",
      },
      answer: "b",
      topic: "digital_logic",
      source: {
        artifact: { artifact_id: "art_gate_dl_paper", version: 1 },
        page: 9,
      },
    },
    {
      id: "q5",
      stem: "Which linear data structure removes elements in First-In, First-Out (FIFO) order?",
      options: {
        a: "Stack",
        b: "Binary heap",
        c: "Queue",
        d: "Depth-first list",
      },
      answer: "c",
      topic: "data_structures",
      source: {
        artifact: { artifact_id: "art_gate_ds_notes", version: 2 },
        page: 1,
      },
    },
    {
      id: "q6",
      stem: "What is the worst-case height of an AVL tree containing n nodes?",
      options: {
        a: "Theta(log n)",
        b: "Theta(n)",
        c: "Theta(sqrt(n))",
        d: "Theta(1)",
      },
      answer: "a",
      topic: "data_structures",
      source: {
        artifact: { artifact_id: "art_gate_ds_notes", version: 2 },
        page: 5,
      },
    },
    {
      id: "q7",
      stem: "Which traversal of a Binary Search Tree visits keys in non-decreasing sorted order?",
      options: {
        a: "Pre-order",
        b: "In-order",
        c: "Post-order",
        d: "Level-order",
      },
      answer: "b",
      topic: "data_structures",
      source: {
        artifact: { artifact_id: "art_gate_ds_notes", version: 2 },
        page: 8,
      },
    },
    {
      id: "q8",
      stem: "What is the worst-case time complexity of Merge Sort on an array of n elements?",
      options: {
        a: "O(n)",
        b: "O(n log n)",
        c: "O(n^2)",
        d: "O(log n)",
      },
      answer: "b",
      topic: "algorithms",
      source: {
        artifact: { artifact_id: "art_gate_algo_bank", version: 1 },
        page: 3,
      },
    },
    {
      id: "q9",
      stem: "Dijkstra's shortest-path algorithm requires edge weights in the graph to be:",
      options: {
        a: "Strictly positive integers only",
        b: "Non-negative",
        c: "Negative and positive without cycles",
        d: "Sorted in decreasing order",
      },
      answer: "b",
      topic: "algorithms",
      source: {
        artifact: { artifact_id: "art_gate_algo_bank", version: 1 },
        page: 6,
      },
    },
    {
      id: "q10",
      stem: "Using binary search on a sorted array of 1,024 elements takes at most how many comparisons?",
      options: {
        a: "8",
        b: "10",
        c: "11",
        d: "16",
      },
      answer: "c",
      topic: "algorithms",
      source: {
        artifact: { artifact_id: "art_gate_algo_bank", version: 1 },
        page: 11,
      },
    },
  ],
};
