/* Eel abstraction */
let handler = {
  get(target, name) {
    return async (...args) => {
      return eel[name](...args)();
    };
  },
};

const Python = new Proxy({}, handler);
