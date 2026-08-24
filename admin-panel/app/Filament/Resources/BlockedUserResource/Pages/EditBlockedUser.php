<?php

namespace App\Filament\Resources\BlockedUserResource\Pages;

use App\Filament\Resources\BlockedUserResource;
use Filament\Actions;
use Filament\Resources\Pages\EditRecord;

class EditBlockedUser extends EditRecord
{
    protected static string $resource = BlockedUserResource::class;

    protected function getHeaderActions(): array
    {
        return [
            Actions\DeleteAction::make(),
        ];
    }
}
