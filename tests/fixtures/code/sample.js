// Reads a compendium and answers questions about it.
// Everything in this file is invented for the test suite.
import { readFile } from "node:fs/promises";
const helpers = require("./helpers");

/**
 * One search over a loaded compendium.
 */
export class Compendium {
  constructor(parents) {
    this.parents = parents;
  }

  // Returns the parents whose title contains the term.
  search(term) {
    return this.parents.filter((parent) => parent.title.includes(term));
  }
}

// Loads a compendium from a file on disk.
export async function load(path) {
  const text = await readFile(path, "utf8");
  return new Compendium(JSON.parse(text).parents);
}

const summarize = (compendium) => compendium.parents.length;

helpers.register(load);
