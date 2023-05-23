const selectAll = document.getElementById('select-all');
const deleteBtn = document.querySelector('.saved-articles__deleteBtn');
const checkboxes = Array.from(document.querySelectorAll('.saved-articles__checkbox'));
const trs = Array.from(document.querySelectorAll('tr'));

selectAll.addEventListener('click', () => {
    if (selectAll.checked) {
        deleteBtn.classList.toggle('saved-articles__deleteBtn--selected');
        checkboxes.forEach(checkbox => {
            checkbox.checked = true;
        });
        trs.forEach(tr => {
            tr.classList.toggle("selected");
        })
    } else {
        deleteBtn.classList.toggle('saved-articles__deleteBtn--selected');
        checkboxes.forEach(checkbox => {
            checkbox.checked = false;
        });
        trs.forEach(tr => {
            tr.classList.toggle("selected");
        })
    }
});

checkboxes.forEach((checkbox, index) => {
    checkbox.addEventListener('click', () => {
        trs[index + 1].classList.toggle("selected");

        if (checkbox.checked === true) {
            deleteBtn.classList.toggle('saved-articles__deleteBtn--selected');
        } else {
            const isSomeCheckboxSelected = checkboxes.forEach(checkbox => {
                if (checkbox.checked === true) {
                    return true;
                }
            })
            if (!isSomeCheckboxSelected) {
                deleteBtn.classList.toggle('saved-articles__deleteBtn--selected');
            } 
        }
        let j = 0;
        for (let i = 0; i < checkboxes.length; i++) {
            if (trs[i].classList.contains("selected")) {
                j++;
            }
        }
    });
});
