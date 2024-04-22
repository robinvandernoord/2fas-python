import {type TPython, type Eel} from "./_types";

declare var Python: TPython;
declare var eel: Eel;

const $settings = document.getElementById("settings")

async function main() {

    console.log('login main 2',
    await Python.get_settings(),
    $settings)
}

main()
